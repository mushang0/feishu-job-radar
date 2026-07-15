from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import load_config, validate_config
from ..error_safety import safe_exception_detail
from ..integrations.feishu import FeishuIntegrationService
from ..paths import AppPaths
from ..runtime import RunReporter
from ..services.scanning import DailyStageError, DailyWorkflowResult, run_daily_workflow
from ..services.initialization import InitializationService, existing_local_repository
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
        self._snapshot_path = paths.root / "scan-task.json"
        self._restore_snapshot()

    def _restore_snapshot(self) -> None:
        if not self._snapshot_path.is_file():
            return
        try:
            task = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(task, dict) or not task.get("task_id"):
                return
            if task.get("status") in {"queued", "running", "cancelling"}:
                task.update({
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "errors": [{
                        "stage": task.get("stage") or "runtime",
                        "code": "service_restarted",
                        "message": "扫描服务已重启，本次任务未完成。",
                    }],
                })
            self._tasks[str(task["task_id"])] = task
        except (OSError, ValueError, TypeError):
            logging.warning("Ignoring unreadable scan task snapshot")

    def _persist_locked(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: value for key, value in task.items() if key != "future"}
        temporary = self._snapshot_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self._snapshot_path)

    def start(self, kind: str, operation) -> str:
        with self._lock:
            if self._active_task_id:
                active = self._tasks.get(self._active_task_id, {})
                if active.get("status") in {"queued", "running", "cancelling"}:
                    raise RuntimeError(self._active_task_id)
            task_id = uuid4().hex
            self._tasks[task_id] = {
                "task_id": task_id,
                "kind": kind,
                "status": "queued",
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._active_task_id = task_id
            future = self._executor.submit(self._run, task_id, operation)
            self._tasks[task_id]["future"] = future
            self._persist_locked(task_id)
            return task_id

    def _run(self, task_id: str, operation) -> None:
        with self._lock:
            if self._tasks[task_id].get("cancel_requested"):
                self._tasks[task_id]["status"] = "cancelled"
                if self._active_task_id == task_id:
                    self._active_task_id = None
                return
            self._tasks[task_id]["status"] = "running"
            self._persist_locked(task_id)
        try:
            payload = operation(task_id, lambda: self._cancelled(task_id))
            with self._lock:
                task = self._tasks[task_id]
                task.update(payload)
                if task.get("cancel_requested"):
                    task["status"] = "cancelled"
                self._persist_locked(task_id)
        except Exception:
            logging.error("Web background task failed")
            fallback = DailyWorkflowResult(status="failed", task_id=task_id, errors=(DailyStageError("workflow", "workflow_failed", "每日工作流失败"),))
            with self._lock:
                task = self._tasks[task_id]
                task.update(fallback.to_dict())
                if task.get("cancel_requested"):
                    task["status"] = "cancelled"
                self._persist_locked(task_id)
        finally:
            with self._lock:
                self._tasks[task_id]["finished_at"] = datetime.now().isoformat(timespec="seconds")
                self._persist_locked(task_id)
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
            self._persist_locked(task_id)
            return True

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {key: value for key, value in task.items() if key != "future"}

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._active_task_id:
                return None
            task = self._tasks.get(self._active_task_id)
            if not task or task.get("status") not in {"queued", "running", "cancelling"}:
                return None
            return {key: value for key, value in task.items() if key != "future"}

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            finished = [task for task in self._tasks.values() if task.get("finished_at")]
            if not finished:
                return None
            task = max(finished, key=lambda item: str(item.get("finished_at") or ""))
            return {key: value for key, value in task.items() if key != "future"}

    def progress(self, task_id: str, event) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.update({"stage": event.command, "stage_label": event.name,
                             "stage_current": event.step, "stage_total": event.total_steps,
                             "message": event.detail or event.name})
                self._persist_locked(task_id)


def create_app(paths: AppPaths | None = None) -> FastAPI:
    paths = paths or AppPaths.default()
    paths.ensure_runtime_directories()
    state = WebStateService(paths)

    def run_published_scan(config: dict, task_id: str, cancelled) -> dict[str, Any]:
        """Build a complete scan in isolation and publish it with one atomic swap."""
        staging = paths.root / f"jobs.{task_id}.staging.sqlite"
        if paths.database.is_file():
            shutil.copy2(paths.database, staging)
        try:
            result = run_daily_workflow(
                config, staging, task_id=task_id, cancel_check=cancelled,
                reporter=RunReporter(event_sink=lambda event: tasks.progress(task_id, event)),
            )
            if result.status == "success" and not cancelled() and staging.is_file():
                os.replace(staging, paths.database)
            return result.to_dict()
        finally:
            if staging.exists():
                staging.unlink()

    def run_published_local(config: dict, task_id: str, cancelled) -> dict[str, Any]:
        staging = paths.root / f"jobs.{task_id}.staging.sqlite"
        if paths.database.is_file():
            shutil.copy2(paths.database, staging)
        try:
            result = LocalApplicationService(staging, config).initialize_and_update(
                task_id=task_id, cancel_check=cancelled,
                reporter=RunReporter(event_sink=lambda event: tasks.progress(task_id, event)),
            )
            if result.daily.status == "success" and not cancelled() and staging.is_file():
                os.replace(staging, paths.database)
            return result.to_dict()
        finally:
            if staging.exists():
                staging.unlink()
    initialization = InitializationService(paths)
    tasks = TaskManager(paths)
    app = FastAPI(title="JobPicky", version=__version__)
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
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
        from ..core import inspect_local_database
        if inspect_local_database(paths.database).valid:
            from ..services.local import rematch_local
            rematch_local(paths.database, load_config(paths.config))
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
            task_id = tasks.start(
                "local",
                lambda task_id, cancelled: run_published_local(config, task_id, cancelled),
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
    def jobs(page: int = 1, page_size: int = 25, scope: str = "all", query: str = "",
             city: str = "", batch: str = "", direction: str = "", deadline_status: str = "",
             company_type: str = "", sort: str = "deadline", recommended: bool = False) -> dict[str, Any]:
        return state.jobs(page=page, page_size=page_size, scope=scope, query=query, city=city,
                          batch=batch, direction=direction, deadline_status=deadline_status,
                          company_type=company_type, sort=sort, recommended=recommended)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int) -> dict[str, Any]:
        item = state.job_detail(job_id)
        if not item:
            raise HTTPException(status_code=404, detail="岗位不存在")
        return item

    @app.get("/api/scan/status")
    def scan_status() -> dict[str, Any]:
        return state.scan_status(tasks.active(), tasks.latest())

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
            repo = existing_local_repository(paths.database)
        except ValueError:
            raise HTTPException(
                status_code=409,
                detail={
                    "stage": "local_database",
                    "code": "local_database_not_initialized",
                    "message": "本地数据库尚未初始化，请先完成本地初始化后再连接飞书。",
                },
            ) from None

        try:
            client = FeishuIntegrationService(repo, test_config).test_connection()
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
                lambda task_id, cancelled: run_published_scan(config, task_id, cancelled),
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

    @app.get("/api/tasks/active")
    def active_task() -> dict[str, Any]:
        return tasks.active() or {"status": "idle"}

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
