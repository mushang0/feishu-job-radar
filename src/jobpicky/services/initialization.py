from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
        repo = JobRepository(self.paths.database)
        repo.init_schema()
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
