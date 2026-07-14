from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from ..config import validate_config
from ..feishu import FeishuBitableClient
from ..integrations.feishu import FeishuIntegrationService
from ..paths import AppPaths
from ..storage import JobRepository
from ..workspace_schema import desired_workspace
from .synchronization import SyncSummary, sync_feishu


@dataclass(frozen=True, slots=True)
class InitializationPreview:
    base_url: str
    table_name: str
    baseline_items: int
    configured: bool


@dataclass(frozen=True, slots=True)
class InitializationResult:
    table_id: str
    workspace_url: str
    baseline_items: int
    recommended_items: int
    sync: SyncSummary


class InitializationService:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    def preview(self, config: dict[str, Any]) -> InitializationPreview:
        repo = JobRepository(self.paths.database)
        repo.init_schema()
        feishu = config.get("feishu", {})
        return InitializationPreview(
            base_url=str(feishu.get("base_url") or ""),
            table_name=desired_workspace().table_name,
            baseline_items=repo.count_jobs(),
            configured=bool(feishu.get("app_id") and feishu.get("app_secret") and feishu.get("base_url")),
        )

    def initialize(self, config: dict[str, Any], *, client: FeishuBitableClient | None = None) -> InitializationResult:
        errors = validate_config(
            config,
            require_feishu=True,
            require_graduate_years=False,
            require_batches=True,
        )
        if errors:
            raise ValueError("；".join(errors))
        repo = existing_local_repository(self.paths.database)
        result = FeishuIntegrationService(
            repo, config, config_path=self.paths.config, push_jobs=sync_feishu
        ).connect(client=client)
        return InitializationResult(
            table_id=result.table_id,
            workspace_url=result.workspace_url,
            baseline_items=result.baseline_items,
            recommended_items=result.recommended_items,
            sync=result.sync,
        )


def existing_local_repository(database_path: str | Path) -> JobRepository:
    """Open an initialized local database without creating or repairing it."""
    path = Path(database_path)
    message = "本地数据库尚未初始化，请先完成本地初始化后再连接飞书。"
    if not path.is_file():
        raise ValueError(message)
    repo = JobRepository(path)
    try:
        with repo.connect() as connection:
            required = {"jobs", "recommended_jobs", "feishu_sync", "job_user_state"}
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        if not required.issubset(tables):
            raise ValueError(message)
        repo.count_jobs()
    except sqlite3.Error:
        raise ValueError(message) from None
    return repo
