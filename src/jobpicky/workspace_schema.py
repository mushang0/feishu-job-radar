from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WORKSPACE_SCHEMA_VERSION = "6"

FIELD_TYPE_CODES = {
    "text": 1,
    "single_select": 3,
    "date": 5,
    "checkbox": 7,
    "url": 15,
}

JOB_STATUS_OPTIONS = ("待处理", "收藏", "已投递", "笔试中", "面试中", "Offer", "已结束", "不合适")


@dataclass(frozen=True, slots=True)
class WorkspaceField:
    name: str
    field_type: str
    hidden: bool = False
    options: tuple[str, ...] = ()

    @property
    def type_code(self) -> int:
        return FIELD_TYPE_CODES[self.field_type]

    @property
    def property(self) -> dict[str, Any] | None:
        if self.options:
            return {"options": [{"name": option} for option in self.options]}
        if self.field_type == "date":
            return {"date_formatter": "yyyy/MM/dd"}
        return None

    def create_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"field_name": self.name, "type": self.type_code}
        if self.property is not None:
            payload["property"] = self.property
        return payload


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    name: str
    status_values: tuple[str, ...]
    view_type: str = "grid"
    visible_fields: tuple[str, ...] = ()
    excluded_status_values: tuple[str, ...] = ()

    def create_payload(self) -> dict[str, Any]:
        return {"view_name": self.name, "view_type": self.view_type}


@dataclass(frozen=True, slots=True)
class WorkspaceSchema:
    table_name: str
    primary_field: str
    fields: tuple[WorkspaceField, ...]
    views: tuple[WorkspaceView, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def field(self, name: str) -> WorkspaceField:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)

    def table_create_payload(self) -> dict[str, Any]:
        return {
            "table": {
                "name": self.table_name,
                "default_view_name": self.views[0].name,
                "fields": [field.create_payload() for field in self.fields],
            }
        }


def desired_workspace() -> WorkspaceSchema:
    visible_fields = ("公司", "岗位", "招聘摘要", "城市", "批次", "投递入口", "截止时间", "求职状态", "备注", "当前推荐")
    return WorkspaceSchema(
        table_name="求职工作台",
        primary_field="公司",
        fields=(
            WorkspaceField("公司", "text"),
            WorkspaceField("岗位", "text"),
            WorkspaceField("招聘摘要", "text"),
            WorkspaceField("城市", "text"),
            WorkspaceField("批次", "text"),
            WorkspaceField("投递入口", "url"),
            WorkspaceField("截止时间", "date"),
            WorkspaceField("求职状态", "single_select", options=JOB_STATUS_OPTIONS),
            WorkspaceField("备注", "text"),
            WorkspaceField("当前推荐", "checkbox"),
        ),
        views=(
            WorkspaceView("待处理", ("待处理",), visible_fields=visible_fields),
            WorkspaceView("收藏", ("收藏",), view_type="gallery", visible_fields=visible_fields),
            WorkspaceView(
                "投递进度",
                JOB_STATUS_OPTIONS,
                view_type="kanban",
                visible_fields=visible_fields,
                excluded_status_values=("不合适",),
            ),
        ),
    )
