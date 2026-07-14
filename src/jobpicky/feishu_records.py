from __future__ import annotations

from datetime import datetime
from typing import Any

from .workspace_schema import JOB_STATUS_OPTIONS


USER_MANAGED_FIELDS = frozenset({"求职状态", "备注"})


def build_create_fields(row: dict[str, Any]) -> dict[str, Any]:
    fields = build_update_fields(row)
    status = str(row.get("user_status") or "").strip()
    fields["求职状态"] = status if status in JOB_STATUS_OPTIONS else "待处理"
    note = str(row.get("note") or "").strip()
    if note:
        fields["备注"] = note
    return fields


def build_update_fields(row: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "公司": str(row.get("company") or "未命名公司"),
        "岗位": str(row.get("title") or "未命名岗位"),
        "当前推荐": bool(row.get("recommendation_active")),
    }
    _set_text(fields, "城市", row.get("city"))
    _set_text(fields, "届别", row.get("target_graduate_year"))
    _set_text(fields, "批次", row.get("batch"))

    apply_url = row.get("official_url") or row.get("apply_url") or row.get("original_url")
    if apply_url:
        fields["投递入口"] = {"link": str(apply_url), "text": "打开投递入口"}
    _set_date(fields, "截止时间", row.get("deadline"))
    return fields


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


