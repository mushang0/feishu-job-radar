from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from ...alerts import build_daily_message
from ...config import save_config
from ...error_safety import safe_exception_detail
from ...feishu import FeishuBitableClient, FeishuBot, FeishuConfig
from ...pipeline import pull_user_states_from_feishu
from ...storage import JobRepository
from ...workspace_provisioner import WorkspaceProvisioner
from ...workspace_schema import WORKSPACE_SCHEMA_VERSION, desired_workspace
from ...services.synchronization import SyncSummary, sync_feishu


@dataclass(frozen=True, slots=True)
class FeishuIssue:
    stage: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class FeishuSetupResult:
    table_id: str
    workspace_url: str
    baseline_items: int
    recommended_items: int
    sync: SyncSummary


@dataclass(frozen=True, slots=True)
class FeishuPreflightResult:
    base_name: str
    table_name: str
    baseline_items: int
    recommended_items: int
    write_access_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class FeishuRunResult:
    pull_attempted: bool = False
    pull_succeeded: bool = False
    pull_updated: int = 0
    pull_skipped: int = 0
    pull_unknown: int = 0
    sync: SyncSummary = field(default_factory=SyncSummary)
    notification_status: Literal["skipped", "sent", "failed"] = "skipped"
    issues: tuple[FeishuIssue, ...] = ()


class FeishuIntegrationService:
    """The single application boundary for optional Feishu operations."""

    def __init__(
        self,
        repo: JobRepository,
        config: dict[str, Any],
        *,
        config_path=None,
        client_factory: Callable[[FeishuConfig], Any] = FeishuBitableClient,
        bot_factory: Callable[[str], Any] = FeishuBot,
        pull_states: Callable[..., Any] = pull_user_states_from_feishu,
        push_jobs: Callable[..., SyncSummary] = sync_feishu,
    ):
        self.repo = repo
        self.config = config
        self.config_path = config_path
        self.client_factory = client_factory
        self.bot_factory = bot_factory
        self.pull_states = pull_states
        self.push_jobs = push_jobs

    @property
    def configured(self) -> bool:
        value = FeishuConfig.from_config(self.config)
        auth = bool(value.tenant_access_token or (value.app_id and value.app_secret))
        return self.config.get("feishu", {}).get("enabled", True) is not False and bool(value.app_token and value.table_id and auth)

    def test_connection(self):
        client = self.client_factory(FeishuConfig.from_config(self.config))
        client.get_app()
        return client

    def preflight(self) -> FeishuPreflightResult:
        """Validate credentials and read access without changing local or remote state."""
        client = self.client_factory(FeishuConfig.from_config(self.config))
        app = client.get_app()
        rows = self.repo.list_feishu_reconciliation_rows()
        return FeishuPreflightResult(
            base_name=str(app.get("name") or app.get("app_name") or "当前多维表格"),
            table_name=desired_workspace().table_name,
            baseline_items=self.repo.count_jobs(),
            recommended_items=sum(bool(row.get("recommendation_active")) for row in rows),
        )

    def connect(self, *, client=None) -> FeishuSetupResult:
        """Test, provision and push existing local query results; never rebuild them."""
        client = client or self.test_connection()
        feishu = self.config.setdefault("feishu", {})

        def persist_table_id(table_id: str) -> None:
            feishu["workspace_table_id"] = table_id
            if self.config_path:
                save_config(self.config, self.config_path)

        provisioned = WorkspaceProvisioner(client, desired_workspace()).provision(
            feishu.get("workspace_table_id") or None,
            on_table_created=persist_table_id,
        )
        feishu["workspace_table_id"] = provisioned.table_id
        feishu["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        if self.config_path:
            save_config(self.config, self.config_path)
        rows = self.repo.list_feishu_reconciliation_rows()
        sync = self.push_jobs(self.repo, self.config, rows, client_factory=lambda _config: client)
        feishu.update(
            {
                "enabled": True,
                "workspace_url": provisioned.workspace_url,
                "last_sync_at": datetime.now().isoformat(timespec="seconds"),
                "last_sync_summary": {
                    "created": sync.created,
                    "updated": sync.updated,
                    "skipped": sync.skipped,
                    "failed": sync.failed,
                    "error": sync.error,
                },
                "baseline_items": self.repo.count_jobs(),
                "recommended_items": sum(bool(row.get("recommendation_active")) for row in rows),
                "last_error": sync.error,
            }
        )
        if not sync.failed:
            feishu["last_successful_sync_at"] = feishu["last_sync_at"]
        if self.config_path:
            save_config(self.config, self.config_path)
        return FeishuSetupResult(
            table_id=provisioned.table_id,
            workspace_url=provisioned.workspace_url,
            baseline_items=self.repo.count_jobs(),
            recommended_items=sum(bool(row.get("recommendation_active")) for row in rows),
            sync=sync,
        )

    def run_after_local_update(
        self,
        *,
        new_items: int,
        notification_rows: list[dict[str, Any]],
        fetch_error: str | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> FeishuRunResult:
        if not self.configured:
            return FeishuRunResult()
        issues: list[FeishuIssue] = []
        pull_updated = pull_skipped = pull_unknown = 0
        pull_succeeded = False
        client = None
        try:
            client = self.client_factory(FeishuConfig.from_config(self.config))
            recovery = self.pull_states(self.repo, client)
            pull_updated = int(recovery.updated_count)
            pull_skipped = len(recovery.skipped_record_ids)
            pull_unknown = len(recovery.unknown_statuses)
            pull_succeeded = not (pull_skipped or pull_unknown)
            if not pull_succeeded:
                issues.append(FeishuIssue("feishu_pull", "feishu_pull_anomalies", f"飞书存在异常记录（跳过 {pull_skipped} 条，未知状态 {pull_unknown} 条）"))
        except Exception as exc:
            logging.warning("Feishu state pull failed: %s", safe_exception_detail(exc, self.config))
            issues.append(FeishuIssue("feishu_pull", "feishu_pull_failed", "飞书状态回拉失败"))

        sync = SyncSummary()
        if pull_succeeded and not cancelled():
            try:
                sync = self.push_jobs(
                    self.repo, self.config, self.repo.list_feishu_reconciliation_rows(),
                    client_factory=(lambda _config: client),
                )
                if sync.failed:
                    issues.append(FeishuIssue("feishu_sync", "feishu_sync_failed", f"飞书同步失败 {sync.failed} 条"))
            except Exception as exc:
                logging.error("Feishu sync failed: %s", safe_exception_detail(exc, self.config))
                issues.append(FeishuIssue("feishu_sync", "feishu_sync_failed", "飞书同步失败"))

        notification_status: Literal["skipped", "sent", "failed"] = "skipped"
        webhook = FeishuConfig.from_config(self.config).webhook_url
        if webhook:
            try:
                result = self.bot_factory(webhook).send_text(build_daily_message(new_items, notification_rows, fetch_error))
                notification_status = "sent" if getattr(result, "sent", None) is True else "failed"
            except Exception as exc:
                logging.error("Feishu notification failed: %s", safe_exception_detail(exc, self.config))
                notification_status = "failed"
            if notification_status == "failed":
                issues.append(FeishuIssue("notification", "notification_send_failed", "飞书通知发送失败"))
        return FeishuRunResult(
            pull_attempted=True, pull_succeeded=pull_succeeded,
            pull_updated=pull_updated, pull_skipped=pull_skipped, pull_unknown=pull_unknown,
            sync=sync, notification_status=notification_status, issues=tuple(issues),
        )
