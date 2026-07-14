"""Transport-independent application services for JobPicky."""

from .bootstrap import (
    DatabaseBootstrapService,
    LocalDatabaseInspection,
    inspect_local_database,
    packaged_seed_job_count,
)
from .daily_update import DailyUpdateService, DailyUpdateSummary
from .ingestion import IngestedJob, IngestionSummary, JobIngestionService
from .matching import MatchingService, MatchingSummary
from .queries import JobQueryService
from .recommendations import RecommendationService

__all__ = [
    "DatabaseBootstrapService",
    "LocalDatabaseInspection",
    "inspect_local_database",
    "packaged_seed_job_count",
    "DailyUpdateService",
    "DailyUpdateSummary",
    "IngestedJob",
    "IngestionSummary",
    "JobIngestionService",
    "MatchingService",
    "MatchingSummary",
    "JobQueryService",
    "RecommendationService",
]
