from __future__ import annotations

import threading
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import load_config, validate_config
from ..error_safety import safe_exception_detail
from ..paths import AppPaths
from ..services.scanning import DailyStageError, DailyWorkflowResult, run_daily_workflow
from ..services.initialization import InitializationService
from ..services.web_state import WebStateService


class PreferencesPayload(BaseModel):
    user_profile: dict[str, list[str]] = Field(default_factory=dict)
    feishu: dict[str, str] = Field(default_factory=dict)


class TaskManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-radar")
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active_task_id: str | None = None

    def start_daily(self, config: dict[str, Any]) -> str:
        with self._lock:
            if self._active_task_id:
                active = self._tasks.get(self._active_task_id, {})
                if active.get("status") in {"queued", "running"}:
                    raise RuntimeError(self._active_task_id)
            task_id = uuid4().hex
            self._tasks[task_id] = {"task_id": task_id, "status": "queued"}
            self._active_task_id = task_id
            future = self._executor.submit(self._run_daily, task_id, config)
            self._tasks[task_id]["future"] = future
            return task_id

    def _run_daily(self, task_id: str, config: dict[str, Any]) -> None:
        with self._lock:
            self._tasks[task_id]["status"] = "running"
        try:
            result = run_daily_workflow(config, self.paths.database, task_id=task_id)
            payload = result.to_dict()
            with self._lock:
                self._tasks[task_id].update(payload)
        except Exception as exc:
            logging.error("Web daily task failed: %s", safe_exception_detail(exc, config))
            fallback = DailyWorkflowResult(
                status="failed",
                task_id=task_id,
                errors=(DailyStageError("workflow", "workflow_failed", "每日工作流失败"),),
            )
            with self._lock:
                self._tasks[task_id].update(fallback.to_dict())
        finally:
            with self._lock:
                if self._active_task_id == task_id:
                    self._active_task_id = None

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {key: value for key, value in task.items() if key != "future"}


def create_app(paths: AppPaths | None = None) -> FastAPI:
    paths = paths or AppPaths.default()
    paths.ensure_runtime_directories()
    state = WebStateService(paths)
    initialization = InitializationService(paths)
    tasks = TaskManager(paths)
    app = FastAPI(title="Feishu Job Radar", version="0.1.0")
    app.state.paths = paths
    app.state.tasks = tasks

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        template = Path(__file__).with_name("templates").joinpath("index.html")
        return template.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return state.health()

    @app.get("/api/preferences")
    def preferences() -> dict[str, Any]:
        return state.preferences()

    @app.put("/api/preferences")
    def update_preferences(payload: PreferencesPayload) -> dict[str, Any]:
        errors = state.save_preferences(payload.model_dump())
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        return state.preferences()

    @app.get("/api/jobs")
    def jobs(limit: int = 100) -> list[dict[str, Any]]:
        return state.jobs(limit)

    @app.get("/api/setup/preview")
    def setup_preview() -> dict[str, Any]:
        config = load_config(paths.config)
        return asdict(initialization.preview(config))

    @app.post("/api/setup/initialize")
    def setup_initialize() -> dict[str, Any]:
        try:
            config = load_config(paths.config)
        except Exception as exc:
            logging.warning(
                "Web initialization configuration load failed: %s",
                safe_exception_detail(exc, {}),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "stage": "initialization",
                    "code": "configuration_invalid",
                    "message": "配置校验失败，请检查配置后重试。",
                },
            ) from None
        try:
            result = initialization.initialize(config)
        except ValueError as exc:
            logging.warning(
                "Web initialization configuration rejected: %s",
                safe_exception_detail(exc, config),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "stage": "initialization",
                    "code": "configuration_invalid",
                    "message": "配置校验失败，请检查配置后重试。",
                },
            ) from None
        except Exception as exc:
            logging.error(
                "Web initialization failed: %s",
                safe_exception_detail(exc, config),
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "stage": "initialization",
                    "code": "initialization_failed",
                    "message": "初始化失败，请查看日志后重试。",
                },
            ) from None
        return {
            "table_id": result.table_id,
            "workspace_url": result.workspace_url,
            "baseline_items": result.baseline_items,
            "recommended_items": result.recommended_items,
            "sync": asdict(result.sync),
        }

    @app.post("/api/tasks/daily", status_code=202)
    def start_daily() -> dict[str, str]:
        config = load_config(paths.config)
        errors = validate_config(config)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        try:
            task_id = tasks.start_daily(config)
        except RuntimeError:
            raise HTTPException(
                status_code=409,
                detail={
                    "stage": "daily",
                    "code": "already_running",
                    "message": "已有扫描任务运行中，请稍后再试。",
                },
            ) from None
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        result = tasks.get(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return result

    return app


app = create_app()
