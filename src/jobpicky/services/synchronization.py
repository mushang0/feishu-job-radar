from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..feishu import FeishuBitableClient, FeishuConfig
from ..feishu_records import build_create_fields, build_update_fields
from ..error_safety import known_secrets, redact_text
from ..storage import JobRepository


@dataclass(frozen=True, slots=True)
class SyncSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


def sync_feishu(
    repo: JobRepository,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    client_factory: Callable[[FeishuConfig], Any] = FeishuBitableClient,
) -> SyncSummary:
    """Reconcile local candidate rows with Feishu without touching user fields."""
    feishu_config = FeishuConfig.from_config(config)
    has_auth = bool(feishu_config.tenant_access_token or (feishu_config.app_id and feishu_config.app_secret))
    if not (feishu_config.app_token and feishu_config.table_id and has_auth):
        logging.info("feishu sync skipped: workspace credentials are not configured")
        return SyncSummary(skipped=len(rows))

    client = client_factory(feishu_config)
    tracked_statuses = {"收藏", "已投递", "笔试中", "面试中", "Offer", "已结束"}
    to_create: list[dict[str, Any]] = []
    to_update: list[tuple[dict[str, Any], str]] = []
    created = updated = failed = skipped = 0

    for row in rows:
        job_id = int(row.get("job_id", row.get("id")))
        remote_record_id = str(row.get("feishu_record_id") or "")
        should_exist = bool(row.get("recommendation_active")) or row.get("user_status") in tracked_statuses
        if remote_record_id:
            if row.get("sync_status") in (None, "pending", "pending_update", "failed"):
                to_update.append((row, remote_record_id))
            else:
                skipped += 1
            continue
        if should_exist:
            to_create.append(row)
        else:
            repo.mark_sync(job_id, "synced", record_id=None)
            skipped += 1

    if to_create:
        create_result = client.batch_create_records([{"fields": build_create_fields(row)} for row in to_create])
        if not _result_sent(create_result):
            error = _result_error(create_result, config)
            for row in to_create:
                repo.mark_sync(
                    int(row.get("job_id", row.get("id"))),
                    "failed",
                    error=error,
                )
                failed += 1
            logging.info("feishu bitable create failed: %s", error)
        else:
            returned_ids = list(getattr(create_result, "record_ids", []) or [])
            for index, row in enumerate(to_create):
                job_id = int(row.get("job_id", row.get("id")))
                record_id = returned_ids[index] if index < len(returned_ids) else ""
                if record_id:
                    repo.mark_sync(job_id, "synced", record_id=record_id)
                    created += 1
                else:
                    repo.mark_sync(job_id, "failed", error="飞书创建成功但未返回对应 record_id")
                    failed += 1

    if to_update:
        update_records = [
            {"record_id": record_id, "fields": build_update_fields(row)}
            for row, record_id in to_update
        ]
        update_result = client.batch_update_records(update_records)
        if not _result_sent(update_result):
            error = _result_error(update_result, config)
            for row, record_id in to_update:
                repo.mark_sync(
                    int(row.get("job_id", row.get("id"))),
                    "failed",
                    record_id=record_id,
                    error=error,
                )
            failed += len(to_update)
            logging.info("feishu bitable update skipped or failed: %s", error)
            return SyncSummary(created=created, updated=updated, skipped=skipped, failed=failed)
        for row, record_id in to_update:
            repo.mark_sync(int(row.get("job_id", row.get("id"))), "synced", record_id=record_id)
            updated += 1

    return SyncSummary(created=created, updated=updated, skipped=skipped, failed=failed)


def _result_sent(result: Any) -> bool:
    try:
        return result.sent is True
    except BaseException:
        return False


def _result_error(result: Any, config: dict[str, Any]) -> str:
    try:
        value = getattr(result, "error", None) or "飞书同步失败"
    except BaseException:
        value = "飞书同步失败"
    return redact_text(value, secrets=known_secrets(config))
