from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .audit import normalize_status
from .storage import JobRepository


@dataclass(frozen=True, slots=True)
class MigrationItem:
    record_id: str
    action: str
    status: str | None


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    items: tuple[MigrationItem, ...]


def build_migration_plan(repo: JobRepository, records: Iterable[dict[str, Any]]) -> MigrationPlan:
    local_ids = {int(row["id"]) for row in repo.list_stored_jobs()}
    items: list[MigrationItem] = []
    for index, record in enumerate(records, 1):
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
        record_id = str(record.get("record_id") or f"record-{index}")
        try:
            job_id = int(float(str(fields.get("岗位ID", "")).strip()))
        except (TypeError, ValueError):
            job_id = None
        status = normalize_status(str(fields.get("用户状态") or "未看"))
        action = "保留" if job_id in local_ids and status else "隔离"
        items.append(MigrationItem(record_id, action, status))
    return MigrationPlan(tuple(items))


def apply_migration_plan(plan: MigrationPlan, apply_item: Callable[[MigrationItem], None], *, apply: bool) -> int:
    """Apply only after the caller has supplied an explicit --apply confirmation."""
    if not apply:
        return 0
    for item in plan.items:
        apply_item(item)
    return len(plan.items)
