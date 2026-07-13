from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import save_config, validate_config
from ..feishu import FeishuBitableClient, FeishuConfig
from ..paths import AppPaths
from ..pipeline import rematch_existing_jobs
from ..seed import restore_seed_database
from ..storage import JobRepository
from ..workspace_provisioner import WorkspaceProvisioner
from ..workspace_schema import WORKSPACE_SCHEMA_VERSION, desired_workspace
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

    def initialize(self, config: dict[str, Any]) -> InitializationResult:
        errors = validate_config(config, require_feishu=True)
        if errors:
            raise ValueError("；".join(errors))
        restore_seed_database(self.paths.database)
        repo = JobRepository(self.paths.database)
        repo.init_schema()
        client = FeishuBitableClient(FeishuConfig.from_config(config))
        client.get_app()
        feishu = config.setdefault("feishu", {})

        def persist_table_id(table_id: str) -> None:
            feishu["workspace_table_id"] = table_id
            save_config(config, self.paths.config)

        provisioning = WorkspaceProvisioner(client, desired_workspace()).provision(
            feishu.get("workspace_table_id") or None,
            on_table_created=persist_table_id,
        )
        feishu["workspace_table_id"] = provisioning.table_id
        feishu["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        save_config(config, self.paths.config)
        summary = rematch_existing_jobs(repo, config)
        sync = sync_feishu(repo, config, repo.list_feishu_reconciliation_rows())
        return InitializationResult(
            table_id=provisioning.table_id,
            workspace_url=provisioning.workspace_url,
            baseline_items=summary.items_seen,
            recommended_items=summary.recommended_items,
            sync=sync,
        )
