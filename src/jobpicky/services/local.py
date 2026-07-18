from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Callable

from ..core import (
    DatabaseBootstrapService,
    MatchingService,
    RecommendationService,
    inspect_local_database,
)
from .scanning import DailyWorkflowResult, run_daily_workflow
from ..runtime import RunReporter


@dataclass(frozen=True, slots=True)
class LocalInitializationResult:
    seeded: bool
    baseline_items: int
    baseline_recommended_items: int
    daily: DailyWorkflowResult
    current_recommended_total: int = 0
    new_recommended_count: int | None = None

    def to_dict(self) -> dict:
        payload = self.daily.to_dict()
        new_recommended_count = (
            self.daily.recommended_count
            if self.new_recommended_count is None
            else self.new_recommended_count
        )
        payload.update(
            {
                "mode": "local",
                "seeded": self.seeded,
                "baseline_items": self.baseline_items,
                "baseline_recommended_items": self.baseline_recommended_items,
                "recommended_items": new_recommended_count,
                "new_recommended_count": new_recommended_count,
                "current_recommended_total": self.current_recommended_total,
                "recommendation_delta": new_recommended_count,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class LocalRematchResult:
    items_seen: int
    new_items: int
    updated_items: int
    relevant_items: int
    recommended_items: int
    matched_items: int
    added_recommended_items: int
    removed_recommended_items: int


class LocalApplicationService:
    """Compose local entry-point use cases exclusively from shared core services."""

    def __init__(self, database_path: str | Path, config: dict):
        self.database_path = Path(database_path)
        self.config = config

    def initialize_and_update(
        self,
        *,
        task_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        reporter: RunReporter | None = None,
    ) -> LocalInitializationResult:
        reporter = reporter or RunReporter()
        reporter.stage("daily", 1, 6, "准备扫描", detail="正在载入本地岗位基线")
        database_was_initialized = inspect_local_database(self.database_path).valid
        repository = DatabaseBootstrapService(self.database_path).initialize()
        recommendations_before = {
            int(row["job_id"]) for row in repository.list_recommended_jobs()
        }
        matching = MatchingService(repository, self.config).rematch_all()
        recommended = RecommendationService(repository).rebuild_all(matching.matches)
        local_config = deepcopy(self.config)
        local_config["feishu"] = {}
        daily = run_daily_workflow(
            local_config,
            self.database_path,
            task_id=task_id,
            cancel_check=cancel_check,
            reporter=reporter,
        )
        current_recommendations = repository.list_recommended_jobs()
        return LocalInitializationResult(
            seeded=not database_was_initialized,
            baseline_items=matching.matched_items,
            baseline_recommended_items=recommended,
            current_recommended_total=len(current_recommendations),
            new_recommended_count=len(
                {int(row["job_id"]) for row in current_recommendations}
                - recommendations_before
            ),
            daily=daily,
        )


def rematch_local(database_path: str | Path, config: dict, recommendation_date: str | None = None):
    repository = DatabaseBootstrapService(database_path).initialize()
    items_seen = len(repository.list_stored_jobs())
    recommendations_before = {
        int(row["job_id"]) for row in repository.list_recommended_jobs()
    }
    matching = MatchingService(repository, config).rematch_all()
    recommended = RecommendationService(repository).rebuild_all(
        matching.matches, recommendation_date
    )
    recommendations_after = {
        int(row["job_id"]) for row in repository.list_recommended_jobs()
    }
    return repository, LocalRematchResult(
        items_seen=items_seen,
        new_items=0,
        updated_items=matching.matched_items,
        relevant_items=matching.relevant_items,
        recommended_items=recommended,
        matched_items=matching.matched_items,
        added_recommended_items=len(recommendations_after - recommendations_before),
        removed_recommended_items=len(recommendations_before - recommendations_after),
    )
