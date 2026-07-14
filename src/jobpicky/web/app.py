from __future__ import annotations

from copy import deepcopy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..config import load_config, validate_config
from ..error_safety import safe_exception_detail
from ..feishu import FeishuBitableClient, FeishuConfig
from ..paths import AppPaths
from ..services.scanning import DailyStageError, DailyWorkflowResult, run_daily_workflow
from ..services.initialization import InitializationService
from ..services.local import LocalApplicationService
from ..services.web_state import WebStateService


class PreferencesPayload(BaseModel):
    user_profile: dict[str, list[str]] = Field(default_factory=dict)
    feishu: dict[str, str] = Field(default_factory=dict)


class FeishuTestPayload(BaseModel):
    base_url: str
    app_id: str
    app_secret: str


class TaskManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-radar")
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active_task_id: str | None = None

    def start(self, kind: str, operation) -> str:
        with self._lock:
            if self._active_task_id:
                active = self._tasks.get(self._active_task_id, {})
                if active.get("status") in {"queued", "running"}:
                    raise RuntimeError(self._active_task_id)
            task_id = uuid4().hex
            self._tasks[task_id] = {"task_id": task_id, "kind": kind, "status": "queued"}
            self._active_task_id = task_id
            future = self._executor.submit(self._run, task_id, operation)
            self._tasks[task_id]["future"] = future
            return task_id

    def _run(self, task_id: str, operation) -> None:
        with self._lock:
            if self._tasks[task_id].get("cancel_requested"):
                self._tasks[task_id]["status"] = "cancelled"
                if self._active_task_id == task_id:
                    self._active_task_id = None
                return
            self._tasks[task_id]["status"] = "running"
        try:
            payload = operation(task_id, lambda: self._cancelled(task_id))
            with self._lock:
                self._tasks[task_id].update(payload)
        except Exception:
            logging.error("Web background task failed")
            fallback = DailyWorkflowResult(status="failed", task_id=task_id, errors=(DailyStageError("workflow", "workflow_failed", "每日工作流失败"),))
            with self._lock:
                self._tasks[task_id].update(fallback.to_dict())
        finally:
            with self._lock:
                if self._active_task_id == task_id:
                    self._active_task_id = None

    def _cancelled(self, task_id: str) -> bool:
        with self._lock:
            return bool(self._tasks.get(task_id, {}).get("cancel_requested"))

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.get("status") not in {"queued", "running"}:
                return False
            task["cancel_requested"] = True
            task["status"] = "cancelling"
            future = task.get("future")
            if future and future.cancel():
                task["status"] = "cancelled"
                if self._active_task_id == task_id:
                    self._active_task_id = None
            return True

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
    app = FastAPI(title="JobPicky", version=__version__)
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

    @app.get("/api/onboarding/options")
    def onboarding_options() -> dict[str, Any]:
        return state.onboarding_options()

    @app.put("/api/preferences")
    def update_preferences(payload: PreferencesPayload) -> dict[str, Any]:
        errors = state.save_preferences(payload.model_dump())
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        return state.preferences()

    @app.post("/api/local/start", status_code=202)
    def start_local() -> dict[str, str]:
        config = load_config(paths.config)
        errors = validate_config(
            config,
            require_graduate_years=False,
            require_batches=True,
        )
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        try:
            service = LocalApplicationService(paths.database, config)
            task_id = tasks.start(
                "local",
                lambda task_id, cancelled: service.initialize_and_update(
                    task_id=task_id, cancel_check=cancelled
                ).to_dict(),
            )
        except RuntimeError:
            raise HTTPException(
                status_code=409,
                detail={
                    "stage": "local",
                    "code": "already_running",
                    "message": "已有扫描任务运行中，请稍后再试。",
                },
            ) from None
        return {"task_id": task_id}

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

    @app.post("/api/feishu/test")
    def test_feishu(payload: FeishuTestPayload) -> dict[str, Any]:
        config = load_config(paths.config)
        profile_errors = validate_config(
            config,
            require_graduate_years=False,
            require_batches=True,
        )
        if profile_errors:
            raise HTTPException(status_code=422, detail=profile_errors)

        base_url = payload.base_url.strip()
        app_id = payload.app_id.strip()
        app_secret = payload.app_secret.strip()
        missing = [
            message
            for value, message in (
                (base_url, "请填写飞书多维表格 Base 链接"),
                (app_id, "请填写飞书 App ID"),
                (app_secret, "请填写飞书 App Secret"),
            )
            if not value
        ]
        if missing:
            raise HTTPException(status_code=422, detail=missing)

        test_config = deepcopy(config)
        test_config.setdefault("feishu", {}).update(
            {
                "base_url": base_url,
                "app_id": app_id,
                "app_secret": app_secret,
            }
        )
        try:
            client = FeishuBitableClient(FeishuConfig.from_config(test_config))
            client.get_app()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "stage": "connection",
                    "code": "configuration_invalid",
                    "message": str(exc),
                },
            ) from None
        except Exception as exc:
            logging.warning(
                "Web Feishu connection test failed: %s",
                safe_exception_detail(exc, test_config),
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "stage": "connection",
                    "code": "feishu_connection_failed",
                    "message": "飞书连接测试失败，请检查 Base、App ID、App Secret 和权限。",
                },
            ) from None

        try:
            state.save_feishu_credentials(
                base_url=base_url,
                app_id=app_id,
                app_secret=app_secret,
            )
            result = initialization.initialize(test_config, client=client)
        except ValueError as exc:
            logging.warning(
                "Web Feishu initialization configuration rejected: %s",
                safe_exception_detail(exc, test_config),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "stage": "initialization",
                    "code": "configuration_invalid",
                    "message": "飞书配置校验失败，请检查输入后重试。",
                },
            ) from None
        except Exception as exc:
            logging.error(
                "Web Feishu initialization failed: %s",
                safe_exception_detail(exc, test_config),
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "stage": "initialization",
                    "code": "initialization_failed",
                    "message": "飞书连接成功，但工作台初始化或同步失败；凭据已保存，请重试。",
                },
            ) from None
        return {
            "ok": True,
            "connection_tested": True,
            "table_id": result.table_id,
            "workspace_url": result.workspace_url,
            "baseline_items": result.baseline_items,
            "recommended_items": result.recommended_items,
            "sync": asdict(result.sync),
        }

    @app.post("/api/tasks/daily", status_code=202)
    def start_daily() -> dict[str, str]:
        config = load_config(paths.config)
        errors = validate_config(
            config,
            require_graduate_years=False,
            require_batches=True,
        )
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        try:
            task_id = tasks.start(
                "daily",
                lambda task_id, cancelled: run_daily_workflow(
                    config,
                    paths.database,
                    task_id=task_id,
                    cancel_check=cancelled,
                ).to_dict(),
            )
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

    @app.delete("/api/tasks/{task_id}", status_code=202)
    def cancel_task(task_id: str) -> dict[str, Any]:
        if tasks.get(task_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if not tasks.cancel(task_id):
            raise HTTPException(status_code=409, detail="任务已经结束")
        return tasks.get(task_id) or {"task_id": task_id, "status": "cancelling"}

    return app


app = create_app()
