"""Local PySide6 control panel for Feishu Job Radar.

The UI is deliberately a thin client: commands still use the CLI service and
its RunReporter events, so locking, storage, Feishu handling and cancellation
semantics remain in one place.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import Any

from .config import load_config, save_config
from .onboarding import parse_base_url
from .runtime import RunEvent, RunReport, RunReporter


def apply_form_values(config: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Validate and merge desktop form values without displaying secrets."""
    profile = config.setdefault("user_profile", {})
    feishu = config.setdefault("feishu", {})
    for key in ("graduate_years", "batches", "role_groups", "target_cities", "must_watch_companies"):
        profile[key] = [item.strip() for item in values.get(key, "").replace("，", ",").split(",") if item.strip()]
    for key, label in (("graduate_years", "毕业届别"), ("batches", "招聘批次"), ("role_groups", "岗位方向")):
        if not profile[key]:
            raise ValueError(f"{label}不能为空")
    feishu["base_url"] = values.get("base_url", "").strip()
    parse_base_url(feishu["base_url"])
    feishu["app_id"] = values.get("app_id", "").strip()
    secret = values.get("app_secret", "").strip()
    if secret:
        feishu["app_secret"] = secret
    if not feishu["app_id"] or not feishu.get("app_secret"):
        raise ValueError("App ID 和 App Secret 不能为空")
    return config


try:  # Keep CLI installs usable when the optional desktop dependencies are absent.
    from PySide6.QtCore import QObject, QThread, Signal, Slot
    from PySide6.QtWidgets import (
        QApplication, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
        QMessageBox, QPushButton, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget,
    )
except ImportError:  # pragma: no cover - exercised by packaging/runtime environments
    QApplication = None


if QApplication is not None:
    class CommandWorker(QObject):
        event = Signal(object)
        report = Signal(object)
        completed = Signal(int)
        failed = Signal(str)

        def __init__(self, command: str, config_path: str, db_path: str):
            super().__init__()
            self.command = command
            self.config_path = config_path
            self.db_path = db_path

        @Slot()
        def run(self) -> None:
            try:
                from .cli import main as cli_main
                args = ["--config", self.config_path, "--db", self.db_path, self.command]
                if self.command == "init":
                    args.append("--yes")
                code = cli_main(args, RunReporter(self.event.emit, self.report.emit))
                self.completed.emit(code)
            except Exception as exc:  # Defensive boundary for a worker thread.
                self.failed.emit(str(exc))


    class DesktopWindow(QMainWindow):
        def __init__(self, config_path: str = "config.yaml", db_path: str = "data/jobs.sqlite"):
            super().__init__()
            self.config_path = str(Path(config_path))
            self.db_path = str(Path(db_path))
            self.thread: QThread | None = None
            self.setWindowTitle("飞书求职雷达")
            self.resize(760, 620)
            self._build()
            self._load_form()

        def _build(self) -> None:
            root = QWidget(self)
            layout = QVBoxLayout(root)
            layout.addWidget(QLabel("首次配置（凭据只保存在本机 config.yaml）"))
            form = QFormLayout()
            self.fields: dict[str, QLineEdit] = {}
            labels = {"graduate_years": "毕业届别", "batches": "招聘批次", "role_groups": "岗位方向", "target_cities": "目标城市（可选）", "must_watch_companies": "重点公司（可选）", "base_url": "飞书 Base 链接", "app_id": "App ID", "app_secret": "App Secret"}
            for key, label in labels.items():
                field = QLineEdit()
                if key == "app_secret":
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                self.fields[key] = field
                form.addRow(label, field)
            layout.addLayout(form)
            buttons = QHBoxLayout()
            self.save_button = QPushButton("保存配置")
            self.init_button = QPushButton("首次配置 / 修复工作台")
            self.daily_button = QPushButton("开始每日扫描")
            self.check_button = QPushButton("健康检查")
            self.open_button = QPushButton("打开飞书工作台")
            for button in (self.save_button, self.init_button, self.daily_button, self.check_button, self.open_button):
                buttons.addWidget(button)
            layout.addLayout(buttons)
            self.progress = QProgressBar()
            self.progress.setRange(0, 5)
            layout.addWidget(self.progress)
            self.status = QLabel("准备就绪")
            layout.addWidget(self.status)
            self.output = QPlainTextEdit()
            self.output.setReadOnly(True)
            layout.addWidget(self.output)
            self.setCentralWidget(root)
            self.save_button.clicked.connect(self.save_form)
            self.init_button.clicked.connect(lambda: self.start_command("init"))
            self.daily_button.clicked.connect(lambda: self.start_command("daily"))
            self.check_button.clicked.connect(lambda: self.start_command("check"))
            self.open_button.clicked.connect(self.open_workspace)

        def _load_form(self) -> None:
            config = load_config(self.config_path)
            profile = config.get("user_profile", {})
            for key in ("graduate_years", "batches", "role_groups", "target_cities", "must_watch_companies"):
                self.fields[key].setText(", ".join(profile.get(key, [])))
            feishu = config.get("feishu", {})
            for key in ("base_url", "app_id"):
                self.fields[key].setText(str(feishu.get(key) or ""))

        def _values(self) -> dict[str, str]:
            return {key: field.text() for key, field in self.fields.items()}

        @Slot()
        def save_form(self) -> bool:
            try:
                config = apply_form_values(load_config(self.config_path), self._values())
                save_config(config, self.config_path)
                self.status.setText("配置已保存到本机。")
                return True
            except Exception as exc:
                QMessageBox.warning(self, "无法保存配置", str(exc))
                return False

        def start_command(self, command: str) -> None:
            if command in {"init", "daily"} and not self.save_form():
                return
            if self.thread is not None:
                return
            self.output.clear()
            self.progress.setValue(0)
            self.status.setText("正在运行，请勿关闭窗口。")
            self._set_busy(True)
            self.thread = QThread(self)
            worker = CommandWorker(command, self.config_path, self.db_path)
            worker.moveToThread(self.thread)
            self.thread.started.connect(worker.run)
            worker.event.connect(self.on_event)
            worker.report.connect(self.on_report)
            worker.completed.connect(self.on_complete)
            worker.failed.connect(self.on_failed)
            worker.completed.connect(self.thread.quit)
            worker.failed.connect(self.thread.quit)
            self.thread.finished.connect(worker.deleteLater)
            self.thread.finished.connect(self._thread_finished)
            self.thread.start()

        @Slot(object)
        def on_event(self, event: RunEvent) -> None:
            self.progress.setMaximum(event.total_steps)
            self.progress.setValue(event.step)
            text = f"[{event.step}/{event.total_steps}] {event.name}：{'完成' if event.status == 'done' else '进行中'}"
            if event.detail:
                text += f"（{event.detail}）"
            self.output.appendPlainText(text)

        @Slot(object)
        def on_report(self, report: RunReport) -> None:
            self.output.appendPlainText(report.render())

        @Slot(int)
        def on_complete(self, code: int) -> None:
            self.status.setText("运行完成" if code == 0 else f"运行结束，退出码 {code}")

        @Slot(str)
        def on_failed(self, message: str) -> None:
            self.status.setText("运行失败")
            self.output.appendPlainText(f"错误：{message}")

        def _thread_finished(self) -> None:
            if self.thread is not None:
                self.thread.deleteLater()
            self.thread = None
            self._set_busy(False)

        def _set_busy(self, busy: bool) -> None:
            for button in (self.save_button, self.init_button, self.daily_button, self.check_button, self.open_button):
                button.setEnabled(not busy)

        @Slot()
        def open_workspace(self) -> None:
            try:
                config = load_config(self.config_path)
                url = str(config.get("feishu", {}).get("base_url") or "")
                parse_base_url(url)
                webbrowser.open(url)
                self.status.setText("已请求在浏览器中打开飞书工作台。")
            except Exception as exc:
                QMessageBox.warning(self, "无法打开工作台", str(exc))


def main() -> int:
    if QApplication is None:
        print("未安装桌面依赖。请执行：python -m pip install -e .[desktop]", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    window = DesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
