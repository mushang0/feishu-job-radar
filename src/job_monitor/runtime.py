"""User-facing progress and result reporting shared by CLI and desktop UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True, slots=True)
class RunEvent:
    command: str
    step: int
    total_steps: int
    name: str
    status: str = "running"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RunReport:
    command: str
    status: str
    items_seen: int = 0
    new_items: int = 0
    recommended_items: int = 0
    baseline_items: int | None = None
    current_workspace_items: int | None = None
    feishu_created: int = 0
    feishu_updated: int = 0
    feishu_skipped: int = 0
    feishu_failed: int = 0
    workspace_url: str = ""
    advice: str = ""
    notification_status: str | None = None

    def render(self) -> str:
        heading = {"init": "初始化完成", "daily": "今日扫描完成", "rematch": "重新匹配完成", "check": "健康检查完成", "pull": "飞书状态回收完成"}.get(self.command, "运行完成")
        state = {
            "success": "完成",
            "partial": "部分完成",
            "failed": "失败",
        }.get(self.status, self.status)
        lines = [f"\n{heading}（{state}）"]
        if self.baseline_items is not None:
            lines.append(f"- 本地岗位基线：{self.baseline_items} 条")
        if self.command == "daily":
            lines.extend([f"- 抓取岗位：{self.items_seen} 条", f"- 新发现：{self.new_items} 条", f"- 新推荐：{self.recommended_items} 条"])
        elif self.command in {"init", "rematch"}:
            lines.extend([f"- 参与匹配岗位：{self.items_seen} 条", f"- 推荐岗位：{self.recommended_items} 条"])
        lines.extend([f"- 飞书新增：{self.feishu_created} 条", f"- 飞书更新：{self.feishu_updated} 条"])
        if self.notification_status is not None:
            notification_label = {
                "skipped": "已跳过",
                "sent": "已发送",
                "failed": "失败",
            }.get(self.notification_status, self.notification_status)
            lines.append(f"- 每日通知：{notification_label}")
        if self.current_workspace_items is not None:
            lines.append(f"- 当前工作台岗位：{self.current_workspace_items} 条")
        if self.workspace_url:
            lines.append(f"- 飞书工作台：{self.workspace_url}")
        if self.advice:
            lines.append(f"结论：{self.advice}")
        return "\n".join(lines)


class RunReporter:
    """Small observer API so UI code can consume the same execution lifecycle."""
    def __init__(self, event_sink: Callable[[RunEvent], None] | None = None, report_sink: Callable[[RunReport], None] | None = None):
        self.event_sink = event_sink
        self.report_sink = report_sink

    def stage(self, command: str, step: int, total: int, name: str, status: str = "running", detail: str = "") -> None:
        if self.event_sink:
            self.event_sink(RunEvent(command, step, total, name, status, detail))

    def finish(self, report: RunReport) -> None:
        if self.report_sink:
            self.report_sink(report)


def console_event(event: RunEvent) -> None:
    suffix = f"，{event.detail}" if event.detail else ""
    state = "完成" if event.status == "done" else "开始"
    print(f"[{event.step}/{event.total_steps}] {event.name}……{state}{suffix}", flush=True)


def console_report(report: RunReport) -> None:
    print(report.render(), flush=True)
