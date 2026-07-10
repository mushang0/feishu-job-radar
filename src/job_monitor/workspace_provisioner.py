from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .workspace_schema import WorkspaceField, WorkspaceSchema, WorkspaceView


class WorkspaceConflictError(RuntimeError):
    pass


class WorkspaceVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisioningResult:
    table_id: str
    table_created: bool
    fields_created: tuple[str, ...]
    fields_updated: tuple[str, ...]
    views_created: tuple[str, ...]
    views_updated: tuple[str, ...]
    workspace_url: str


class WorkspaceProvisioner:
    def __init__(self, client, schema: WorkspaceSchema):
        self.client = client
        self.schema = schema

    def provision(
        self,
        table_id: str | None,
        *,
        on_table_created: Callable[[str], None],
    ) -> ProvisioningResult:
        tables = self.client.list_tables()
        table_created = False
        if table_id:
            table = next((item for item in tables if item.get("table_id") == table_id), None)
            if table is None:
                raise WorkspaceConflictError(f"已保存的飞书工作台不存在：{table_id}")
            if table.get("name") != self.schema.table_name:
                raise WorkspaceConflictError(f"工作台名称不匹配：{table.get('name') or table_id}")
        else:
            same_name = [item for item in tables if item.get("name") == self.schema.table_name]
            if same_name:
                raise WorkspaceConflictError(f"发现未接管的同名数据表：{self.schema.table_name}")
            created = self.client.create_table(self.schema.table_create_payload())
            table_id = str(created.get("table_id") or "")
            if not table_id:
                raise WorkspaceVerificationError("飞书创建数据表成功但未返回 table_id")
            on_table_created(table_id)
            table_created = True

        fields_created, fields_updated = self._reconcile_fields(table_id)
        fields = self.client.list_fields(table_id)
        views_created, views_updated = self._reconcile_views(table_id, fields)
        self.verify(table_id)
        app_token = str(getattr(self.client.config, "app_token", ""))
        base_url = str(getattr(self.client.config, "base_url", "") or "").split("?", 1)[0].rstrip("/")
        if not base_url:
            base_url = f"https://feishu.cn/base/{app_token}"
        return ProvisioningResult(
            table_id=table_id,
            table_created=table_created,
            fields_created=tuple(fields_created),
            fields_updated=tuple(fields_updated),
            views_created=tuple(views_created),
            views_updated=tuple(views_updated),
            workspace_url=f"{base_url}?table={table_id}",
        )

    def verify(self, table_id: str) -> None:
        table = next((item for item in self.client.list_tables() if item.get("table_id") == table_id), None)
        if table is None or table.get("name") != self.schema.table_name:
            raise WorkspaceVerificationError("飞书工作台数据表回读失败")

        fields = self.client.list_fields(table_id)
        fields_by_name = {str(item.get("field_name")): item for item in fields}
        for expected in self.schema.fields:
            actual = fields_by_name.get(expected.name)
            if actual is None or actual.get("type") != expected.type_code:
                raise WorkspaceVerificationError(f"字段回读不一致：{expected.name}")
            if expected.name == self.schema.primary_field and not actual.get("is_primary"):
                raise WorkspaceVerificationError(f"主字段回读不一致：{expected.name}")
            self._verify_options(expected, actual, WorkspaceVerificationError)

        views = self.client.list_views(table_id)
        views_by_name = {str(item.get("view_name")): item for item in views}
        for expected in self.schema.views:
            summary = views_by_name.get(expected.name)
            if summary is None or summary.get("view_type") != expected.view_type:
                raise WorkspaceVerificationError(f"视图回读不一致：{expected.name}")
            actual = self.client.get_view(table_id, str(summary["view_id"]))
            desired_property = self._view_property(expected, fields)
            if not self._view_property_matches(actual.get("property") or {}, desired_property):
                raise WorkspaceVerificationError(f"视图配置回读不一致：{expected.name}")

    def _reconcile_fields(self, table_id: str) -> tuple[list[str], list[str]]:
        fields = self.client.list_fields(table_id)
        by_name = {str(item.get("field_name")): item for item in fields}
        created: list[str] = []
        updated: list[str] = []
        for expected in self.schema.fields:
            actual = by_name.get(expected.name)
            if actual is None:
                self.client.create_field(table_id, expected.create_payload())
                created.append(expected.name)
                continue
            if actual.get("type") != expected.type_code:
                raise WorkspaceConflictError(f"字段类型冲突，无法安全修复：{expected.name}")
            if self._options_need_update(expected, actual):
                self.client.update_field(table_id, str(actual["field_id"]), expected.create_payload())
                updated.append(expected.name)
        return created, updated

    def _reconcile_views(self, table_id: str, fields: list[dict]) -> tuple[list[str], list[str]]:
        views = self.client.list_views(table_id)
        by_name = {str(item.get("view_name")): item for item in views}
        created: list[str] = []
        updated: list[str] = []
        for expected in self.schema.views:
            summary = by_name.get(expected.name)
            if summary is None:
                summary = self.client.create_view(table_id, expected.create_payload())
                created.append(expected.name)
            if summary.get("view_type") != expected.view_type:
                raise WorkspaceConflictError(f"视图类型冲突，无法安全修复：{expected.name}")
            view_id = str(summary.get("view_id") or "")
            actual = self.client.get_view(table_id, view_id)
            desired_property = self._view_property(expected, fields)
            if not self._view_property_matches(actual.get("property") or {}, desired_property):
                self.client.update_view(
                    table_id,
                    view_id,
                    {"view_name": expected.name, "property": desired_property},
                )
                updated.append(expected.name)
        return created, updated

    def _view_property(self, view: WorkspaceView, fields: list[dict]) -> dict:
        field_ids = {str(item.get("field_name")): str(item.get("field_id")) for item in fields}
        conditions = [
            {
                "field_id": field_ids["求职状态"],
                "operator": "is",
                "value": json.dumps(list(view.status_values), ensure_ascii=False),
            }
        ]
        if view.require_recommended:
            conditions.append(
                {
                    "field_id": field_ids["推荐有效"],
                    "operator": "is",
                    "value": json.dumps([True]),
                }
            )
        hidden_fields = [field_ids[name] for name in self.schema.field_names if name not in view.visible_fields]
        return {
            "filter_info": {"conjunction": "and", "conditions": conditions},
            "hidden_fields": hidden_fields,
        }

    @staticmethod
    def _view_property_matches(actual: dict, desired: dict) -> bool:
        actual_filter = actual.get("filter_info") or {}
        desired_filter = desired["filter_info"]

        def normalized(conditions):
            return sorted(
                (
                    str(item.get("field_id")),
                    str(item.get("operator")),
                    str(item.get("value")),
                )
                for item in conditions or []
            )

        return (
            actual_filter.get("conjunction") == desired_filter["conjunction"]
            and normalized(actual_filter.get("conditions")) == normalized(desired_filter["conditions"])
            and set(actual.get("hidden_fields") or []) == set(desired["hidden_fields"])
        )

    @staticmethod
    def _option_names(field: dict) -> tuple[str, ...]:
        options = (field.get("property") or {}).get("options") or []
        return tuple(str(option.get("name")) for option in options if isinstance(option, dict))

    def _options_need_update(self, expected: WorkspaceField, actual: dict) -> bool:
        if not expected.options:
            return False
        actual_names = self._option_names(actual)
        unexpected = set(actual_names) - set(expected.options)
        if unexpected:
            raise WorkspaceConflictError(f"单选字段包含未知选项，无法安全修复：{expected.name}")
        return actual_names != expected.options

    def _verify_options(self, expected: WorkspaceField, actual: dict, error_type) -> None:
        if expected.options and self._option_names(actual) != expected.options:
            raise error_type(f"单选字段选项回读不一致：{expected.name}")
