from dataclasses import dataclass
from datetime import date

from .ingestion import JobIngestionService
from .matching import MatchingService
from .recommendations import RecommendationService


@dataclass(frozen=True, slots=True)
class DailyUpdateSummary:
    items_seen: int
    new_items: int
    updated_items: int
    matched_items: int
    relevant_items: int
    recommended_items: int
    pages_scanned: int = 0


class DailyUpdateService:
    """Orchestrate only fetch -> ingest -> match -> recommendation append."""

    def __init__(self, crawler, ingestion: JobIngestionService, matching: MatchingService, recommendations: RecommendationService):
        self.crawler = crawler
        self.ingestion = ingestion
        self.matching = matching
        self.recommendations = recommendations

    def run(self, recommendation_date: str | None = None) -> DailyUpdateSummary:
        crawl = self.crawler.crawl(mode="daily")
        ingestion = self.ingestion.ingest(crawl.jobs)
        matching = self.matching.match_ingested(ingestion.changed_items)
        recommended = self.recommendations.append_daily(
            matching.matches, recommendation_date or date.today().isoformat()
        )
        return DailyUpdateSummary(
            items_seen=ingestion.items_seen,
            new_items=ingestion.new_items,
            updated_items=ingestion.updated_items,
            matched_items=matching.matched_items,
            relevant_items=matching.relevant_items,
            recommended_items=recommended,
            pages_scanned=crawl.pages_scanned,
        )
