from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import (
    DEFAULT_CONFIG,
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
        if not self.paths.config.is_file():
            for key in ("graduate_years", "batches", "role_groups", "target_cities", "custom_keywords"):
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
            "graduate_years": [f"{year}届" for year in range(2026, 2033)],
        }

    def save_preferences(self, payload: dict[str, Any]) -> list[str]:
        config = load_config(self.paths.config)
        profile = config.setdefault("user_profile", {})
        incoming_profile = payload.get("user_profile") or {}
        for key in (
            "graduate_years",
            "batches",
            "role_groups",
            "target_cities",
            "custom_keywords",
            "must_watch_companies",
        ):
            if key in incoming_profile:
                profile[key] = _list_values(incoming_profile[key])

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

    def jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        repo = DatabaseBootstrapService(self.paths.database).initialize()
        rows = JobQueryService(repo).jobs()
        return rows[: max(0, min(limit, 500))]

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
