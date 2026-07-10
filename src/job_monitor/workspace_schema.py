from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkspaceField:
    name: str
    field_type: str
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    name: str
    status_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceSchema:
    primary_field: str
    fields: tuple[WorkspaceField, ...]
    views: tuple[WorkspaceView, ...]


def desired_workspace() -> WorkspaceSchema:
    return WorkspaceSchema(
        primary_field="岗位",
        fields=(
            WorkspaceField("岗位", "text"),
            WorkspaceField("公司", "text"),
            WorkspaceField("城市", "text"),
            WorkspaceField("届别", "text"),
            WorkspaceField("批次", "text"),
            WorkspaceField("推荐理由", "text"),
            WorkspaceField("投递入口", "url"),
            WorkspaceField("截止时间", "date"),
            WorkspaceField("求职状态", "single_select"),
            WorkspaceField("下一步行动", "text"),
            WorkspaceField("备注", "text"),
            WorkspaceField("岗位ID", "text", hidden=True),
            WorkspaceField("来源详情", "url", hidden=True),
            WorkspaceField("同步状态", "text", hidden=True),
        ),
        views=(
            WorkspaceView("待处理", ("待处理",)),
            WorkspaceView("收藏", ("收藏",)),
            WorkspaceView("投递进度", ("收藏", "已投递", "笔试中", "面试中", "Offer", "已结束")),
        ),
    )
