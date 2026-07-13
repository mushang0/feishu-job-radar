from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import DEFAULT_CONFIG, load_config, save_config, validate_config
from ..onboarding import parse_base_url
from ..paths import AppPaths
from ..storage import JobRepository


class WebStateService:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    def preferences(self) -> dict[str, Any]:
        config = load_config(self.paths.config)
        profile = deepcopy(config.get("user_profile", {}))
        feishu = config.get("feishu", {})
        return {
            "user_profile": profile,
            "feishu": {
                "base_url": feishu.get("base_url", ""),
                "app_id": feishu.get("app_id", ""),
                "configured": bool(feishu.get("app_secret")),
            },
        }

    def save_preferences(self, payload: dict[str, Any]) -> list[str]:
        config = load_config(self.paths.config)
        profile = config.setdefault("user_profile", {})
        incoming_profile = payload.get("user_profile") or {}
        for key in ("graduate_years", "batches", "role_groups", "target_cities", "must_watch_companies"):
            if key in incoming_profile:
                profile[key] = [str(item).strip() for item in incoming_profile[key] if str(item).strip()]

        incoming_feishu = payload.get("feishu") or {}
        feishu = config.setdefault("feishu", {})
        if "base_url" in incoming_feishu:
            feishu["base_url"] = str(incoming_feishu["base_url"]).strip()
            if feishu["base_url"]:
                parse_base_url(feishu["base_url"])
        for key in ("app_id", "app_secret"):
            if key in incoming_feishu and str(incoming_feishu[key]).strip():
                feishu[key] = str(incoming_feishu[key]).strip()

        errors = validate_config(config, require_feishu=False)
        if errors:
            return errors
        save_config(config, self.paths.config)
        return []

    def jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        repo = JobRepository(self.paths.database)
        repo.init_schema()
        rows = repo.list_all_jobs()
        return rows[: max(0, min(limit, 500))]

    def health(self) -> dict[str, Any]:
        repo = JobRepository(self.paths.database)
        repo.init_schema()
        config = load_config(self.paths.config)
        return {
            "config_exists": self.paths.config.is_file(),
            "database_exists": self.paths.database.is_file(),
            "job_count": repo.count_jobs(),
            "configuration_errors": validate_config(config),
        }
