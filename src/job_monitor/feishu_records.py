from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .workspace_schema import JOB_STATUS_OPTIONS


USER_MANAGED_FIELDS = frozenset({"求职状态", "下次行动", "备注"})


@dataclass(frozen=True, slots=True)
class RemoteRecordIndex:
    by_job_id: dict[int, str]
    duplicate_job_ids: frozenset[int]
    invalid_record_ids: tuple[str, ...]


def build_create_fields(row: dict[str, Any]) -> dict[str, Any]:
    fields = build_update_fields(row)
    status = str(row.get("user_status") or "").strip()
    fields["求职状态"] = status if status in JOB_STATUS_OPTIONS else "待处理"
    next_action = str(row.get("next_action") or "").strip()
    note = str(row.get("note") or "").strip()
    if next_action:
        fields["下次行动"] = next_action
    if note:
        fields["备注"] = note
    return fields


def build_update_fields(row: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "岗位": str(row.get("title") or "未命名岗位"),
        "岗位ID": str(row.get("job_id") or row.get("id") or ""),
        "推荐有效": bool(row.get("recommendation_active")),
    }
    _set_text(fields, "公司", row.get("company"))
    _set_text(fields, "城市", row.get("city"))
    _set_text(fields, "届别", row.get("target_graduate_year"))
    _set_text(fields, "批次", row.get("batch"))
    _set_text(fields, "推荐理由", row.get("recommend_reason"))

    apply_url = row.get("official_url") or row.get("apply_url") or row.get("original_url")
    if apply_url:
        fields["投递入口"] = {"link": str(apply_url), "text": "打开投递入口"}
    source_url = row.get("original_url")
    if source_url:
        fields["来源详情"] = {"link": str(source_url), "text": "查看来源"}

    _set_date(fields, "截止时间", row.get("deadline"))
    _set_date(fields, "首次发现", row.get("first_seen"))
    _set_date(fields, "最后更新", row.get("last_seen"))
    return fields


def index_remote_records(records: Iterable[dict[str, Any]]) -> RemoteRecordIndex:
    by_job_id: dict[int, str] = {}
    duplicates: set[int] = set()
    invalid: list[str] = []
    for index, record in enumerate(records, 1):
        record_id = str(record.get("record_id") or f"record-{index}")
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
        try:
            job_id = int(float(_text(fields.get("岗位ID")).strip()))
        except (TypeError, ValueError):
            invalid.append(record_id)
            continue
        if job_id in by_job_id or job_id in duplicates:
            duplicates.add(job_id)
            by_job_id.pop(job_id, None)
            continue
        by_job_id[job_id] = record_id
    return RemoteRecordIndex(by_job_id, frozenset(duplicates), tuple(invalid))


def _set_text(fields: dict[str, Any], name: str, value: Any) -> None:
    if value not in (None, ""):
        fields[name] = str(value)


def _set_date(fields: dict[str, Any], name: str, value: Any) -> None:
    timestamp = _timestamp_ms(value)
    if timestamp is not None:
        fields[name] = timestamp


def _timestamp_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or "")
    return "" if value is None else str(value)
