from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import validate_config
from ..core import inspect_local_database, packaged_seed_job_count
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
        inspection = inspect_local_database(self.paths.database)
        feishu = config.get("feishu", {})
        return InitializationPreview(
            base_url=str(feishu.get("base_url") or ""),
            table_name=desired_workspace().table_name,
            baseline_items=(
                inspection.job_count if inspection.valid else packaged_seed_job_count()
            ),
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
    if not inspect_local_database(path).valid:
        raise ValueError(message)
    return JobRepository(path)
