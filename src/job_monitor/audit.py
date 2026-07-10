from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .storage import JobRepository


KNOWN_STATUSES = frozenset({"待处理", "收藏", "不合适", "已投递", "笔试中", "面试中", "Offer", "已结束"})


@dataclass(frozen=True, slots=True)
class FeishuAuditReport:
    local_job_count: int
    remote_record_count: int
    only_local_job_ids: list[int] = field(default_factory=list)
    only_remote_record_ids: list[str] = field(default_factory=list)
    duplicate_job_ids: list[int] = field(default_factory=list)
    blank_record_ids: list[str] = field(default_factory=list)
    unmatched_record_ids: list[str] = field(default_factory=list)
    unknown_statuses: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StateRecoveryResult:
    updated_count: int
    unknown_statuses: dict[str, str]
    skipped_record_ids: list[str]


def audit_feishu_records(repo: JobRepository, records: Iterable[dict[str, Any]]) -> FeishuAuditReport:
    record_list = list(records)
    local_ids = {int(row["id"]) for row in repo.list_stored_jobs()}
    matched_ids: set[int] = set()
    seen_ids: set[int] = set()
    duplicates: set[int] = set()
    only_remote: list[str] = []
    blank: list[str] = []
    unmatched: list[str] = []
    unknown: dict[str, str] = {}

    for index, record in enumerate(record_list):
        record_id = str(record.get("record_id") or f"record-{index + 1}")
        fields = _fields(record)
        job_id = _job_id(fields.get("岗位ID"))
        if fields.get("岗位ID") in (None, "", []):
            blank.append(record_id)
            continue
        if job_id is None:
            unmatched.append(record_id)
            continue
        if job_id in seen_ids:
            duplicates.add(job_id)
        seen_ids.add(job_id)
        if job_id not in local_ids:
            only_remote.append(record_id)
        else:
            matched_ids.add(job_id)
        status = _text(fields.get("求职状态")).strip()
        if status and normalize_status(status) is None:
            unknown[record_id] = status

    return FeishuAuditReport(
        local_job_count=len(local_ids),
        remote_record_count=len(record_list),
        only_local_job_ids=sorted(local_ids - matched_ids),
        only_remote_record_ids=only_remote,
        duplicate_job_ids=sorted(duplicates),
        blank_record_ids=blank,
        unmatched_record_ids=unmatched,
        unknown_statuses=unknown,
    )


def recover_user_states(repo: JobRepository, records: Iterable[dict[str, Any]]) -> StateRecoveryResult:
    report = audit_feishu_records(repo, records)
    skipped = set(report.only_remote_record_ids + report.blank_record_ids + report.unmatched_record_ids)
    updated = 0
    for index, record in enumerate(records):
        record_id = str(record.get("record_id") or f"record-{index + 1}")
        if record_id in skipped or record_id in report.unknown_statuses:
            continue
        fields = _fields(record)
        job_id = _job_id(fields.get("岗位ID"))
        status = normalize_status(_text(fields.get("求职状态")).strip())
        if job_id is None or status is None:
            continue
        repo.update_user_state(
            job_id,
            status,
            _text(fields.get("备注")),
            apply_url_manual=None,
            next_action=_text(fields.get("下次行动")),
        )
        if record.get("record_id"):
            repo.mark_sync(job_id, "synced", record_id=str(record["record_id"]))
        updated += 1
    return StateRecoveryResult(updated_count=updated, unknown_statuses=report.unknown_statuses, skipped_record_ids=sorted(skipped))


def normalize_status(value: str) -> str | None:
    return value if value in KNOWN_STATUSES else None


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", {})
    return fields if isinstance(fields, dict) else {}


def _job_id(value: Any) -> int | None:
    try:
        return int(float(_text(value).strip()))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or "")
    return "" if value is None else str(value)


def _link_or_text(value: Any) -> str:
    return _text(value)
