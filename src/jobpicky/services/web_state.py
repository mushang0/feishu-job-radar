from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..config import (
    DEFAULT_CONFIG,
    LEGACY_DEFAULT_EXCLUDED_ROLES,
    ONBOARDING_BATCH_OPTIONS,
    ONBOARDING_ROLE_SECTIONS,
    load_config,
    save_config,
    validate_config,
)
from ..onboarding import parse_base_url
from ..normalizer import KNOWN_CITY_NAMES
from ..paths import AppPaths
from ..core import DatabaseBootstrapService, JobQueryService


class WebStateService:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    def preferences(self) -> dict[str, Any]:
        config = load_config(self.paths.config)
        profile = deepcopy(config.get("user_profile", {}))
        if set(profile.get("exclude_role_groups", [])) == set(LEGACY_DEFAULT_EXCLUDED_ROLES):
            profile["exclude_role_groups"] = []
        if not self.paths.config.is_file():
            for key in ("batches", "role_groups", "target_cities", "custom_keywords", "exclude_role_groups"):
                profile[key] = []
        feishu = config.get("feishu", {})
        configuration_errors = validate_config(
            config,
            require_graduate_years=False,
            require_batches=True,
        )
        return {
            "user_profile": profile,
            "feishu": {
                "base_url": feishu.get("base_url", ""),
                "app_id": feishu.get("app_id", ""),
                "configured": bool(feishu.get("base_url") and feishu.get("app_id") and feishu.get("app_secret")),
                "workspace_configured": bool(feishu.get("workspace_table_id")),
            },
            "onboarding_complete": self.paths.config.is_file() and not configuration_errors,
        }

    def onboarding_options(self) -> dict[str, Any]:
        return {
            "batches": [{"value": value, "label": value} for value in ONBOARDING_BATCH_OPTIONS],
            "role_sections": deepcopy(list(ONBOARDING_ROLE_SECTIONS)),
            "cities": [{"value": "", "label": "不限"}]
            + [{"value": city, "label": city} for city in KNOWN_CITY_NAMES],
            "exclude_role_sections": deepcopy(list(ONBOARDING_ROLE_SECTIONS)),
        }

    def save_preferences(self, payload: dict[str, Any]) -> list[str]:
        config = load_config(self.paths.config)
        profile = config.setdefault("user_profile", {})
        incoming_profile = payload.get("user_profile") or {}
        for key in (
            "batches",
            "role_groups",
            "exclude_role_groups",
            "target_cities",
            "custom_keywords",
            "must_watch_companies",
        ):
            if key in incoming_profile:
                profile[key] = _list_values(incoming_profile[key])
        if set(profile.get("exclude_role_groups", [])) == set(LEGACY_DEFAULT_EXCLUDED_ROLES):
            profile["exclude_role_groups"] = []

        incoming_feishu = payload.get("feishu") or {}
        feishu = config.setdefault("feishu", {})
        try:
            if "base_url" in incoming_feishu:
                feishu["base_url"] = str(incoming_feishu["base_url"]).strip()
                if feishu["base_url"]:
                    parse_base_url(feishu["base_url"])
            for key in ("app_id", "app_secret"):
                if key in incoming_feishu and str(incoming_feishu[key]).strip():
                    feishu[key] = str(incoming_feishu[key]).strip()
        except ValueError as exc:
            return [str(exc)]

        errors = validate_config(
            config,
            require_feishu=False,
            require_graduate_years=False,
            require_batches=True,
        )
        if errors:
            return errors
        save_config(config, self.paths.config)
        return []

    def save_feishu_credentials(self, *, base_url: str, app_id: str, app_secret: str) -> None:
        config = load_config(self.paths.config)
        parsed_base_url = str(base_url).strip()
        parse_base_url(parsed_base_url)
        feishu = config.setdefault("feishu", {})
        feishu.update(
            {
                "base_url": parsed_base_url,
                "app_id": str(app_id).strip(),
                "app_secret": str(app_secret).strip(),
            }
        )
        save_config(config, self.paths.config)

    def jobs(self, *, page: int = 1, page_size: int = 25, scope: str = "all", query: str = "",
             city: str = "", batch: str = "", direction: str = "", deadline_status: str = "",
             company_type: str = "", sort: str = "deadline", recommended: bool = False) -> dict[str, Any]:
        if not self.paths.database.is_file():
            return {"items": [], "page": 1, "page_size": page_size, "total": 0, "pages": 0,
                    "summary": {"all": 0, "recommended": 0, "today_recommended": 0,
                                "new_recommended": 0, "expiring": 0},
                    "facets": {"cities": [], "batches": [], "company_types": [], "directions": []}}
        # Reads must never bootstrap/restore the packaged seed database.
        from ..storage import JobRepository
        repo = JobRepository(self.paths.database)
        queries = JobQueryService(repo)
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        recommended = recommended or scope in {"recommended", "today", "new", "expiring"}
        today_since = (date.today() - timedelta(days=1)).isoformat()
        new_since = today_since if scope in {"today", "new"} else ""
        if scope == "expiring":
            deadline_status = "expiring"
        items, total = repo.search_jobs(
            recommended=recommended, query=query.strip(), city=city, batch=batch,
            direction=direction, deadline_status=deadline_status, company_type=company_type,
            new_since=new_since, sort=sort, limit=page_size, offset=(page - 1) * page_size,
        )
        stats = queries.stats()
        for item in items:
            item["detail_url"] = item.pop("original_url", None)
            apply_url = str(item.get("apply_url") or "").strip()
            if not _valid_apply_url(apply_url):
                item["apply_url"] = None
        _, today_recommended_total = repo.search_jobs(
            recommended=True, new_since=today_since, limit=1,
        )
        facets = repo.job_facets()
        facets["directions"] = _list_values(load_config(self.paths.config).get("user_profile", {}).get("role_groups", []))
        return {
            "items": items,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
            "recommended_total": stats["recommendations"],
            "page": page,
            "page_size": page_size,
            "summary": {"all": stats["jobs"], "recommended": stats["recommendations"],
                        "today_recommended": today_recommended_total,
                        "new_recommended": today_recommended_total,
                        "expiring": repo.count_expiring_jobs(recommended=True)},
            "facets": facets,
        }

    def job_detail(self, job_id: int) -> dict[str, Any]:
        if not self.paths.database.is_file():
            return {}
        from ..storage import JobRepository
        item = JobRepository(self.paths.database).get_job_detail(job_id)
        if item:
            item["detail_url"] = item.pop("original_url", None)
            if not _valid_apply_url(str(item.get("apply_url") or "")):
                item["apply_url"] = None
        return item

    def scan_status(self, active_task: dict[str, Any] | None = None,
                    recent_task: dict[str, Any] | None = None) -> dict[str, Any]:
        latest: dict[str, Any] = {}
        last_success: dict[str, Any] = {}
        if self.paths.database.is_file():
            from ..storage import JobRepository
            repo = JobRepository(self.paths.database)
            latest = repo.latest_scan_run()
            last_success = repo.latest_scan_run(successful_only=True)
        if active_task:
            return {
                "state": "running",
                "active_task": active_task,
                "last_run": _scan_summary(latest),
                "last_success_at": last_success.get("finished_at"),
            }
        if recent_task and str(recent_task.get("finished_at") or "") > str(latest.get("finished_at") or ""):
            latest = recent_task
            if recent_task.get("status") == "success":
                last_success = recent_task
        if not latest:
            return {"state": "never", "active_task": None, "last_run": None, "last_success_at": None}
        status = str(latest.get("status") or "failed")
        return {
            "state": "success" if status == "success" else "failed",
            "active_task": None,
            "last_run": _scan_summary(latest),
            "last_success_at": last_success.get("finished_at"),
        }

    def health(self) -> dict[str, Any]:
        repo = DatabaseBootstrapService(self.paths.database).initialize()
        queries = JobQueryService(repo)
        config = load_config(self.paths.config)
        return {
            "config_exists": self.paths.config.is_file(),
            "database_exists": self.paths.database.is_file(),
            "job_count": queries.stats()["jobs"],
            "configuration_errors": validate_config(
                config,
                require_graduate_years=False,
                require_batches=True,
            ),
        }


def _list_values(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _valid_apply_url(value: str) -> bool:
    if not value.lower().startswith(("http://", "https://")):
        return False
    normalized = value.rstrip("/").lower()
    return normalized not in {"https://www.wondercv.com", "http://www.wondercv.com", "https://www.wondercv.com/jobs", "http://www.wondercv.com/jobs"}


def _scan_summary(run: dict[str, Any]) -> dict[str, Any] | None:
    if not run:
        return None
    errors = run.get("errors") or []
    failure_stage = run.get("failure_stage")
    if not failure_stage and errors:
        failure_stage = errors[0].get("stage")
    recommended_items = run.get("recommended_items")
    if recommended_items is None:
        recommended_items = run.get("new_recommended_count", run.get("recommended_count"))
    return {
        "task_id": run.get("task_id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "items_seen": run.get("items_seen", run.get("fetched_count", 0)) or 0,
        "new_items": run.get("new_items", run.get("created_count", 0)) or 0,
        "recommended_items": recommended_items,
        "expiring_items": run.get("expiring_items", 0) or 0,
        "failure_stage": failure_stage,
        "error_message": run.get("error_message") or run.get("error") or "",
    }
