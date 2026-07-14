from datetime import date

from ..storage import JobRepository


class RecommendationService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def append_daily(self, matches, recommendation_date: str | None = None) -> int:
        rows = self._rows(matches)
        self.repository.append_recommendations(recommendation_date or date.today().isoformat(), rows)
        return len(rows)

    def rebuild_all(self, matches, recommendation_date: str | None = None) -> int:
        rows = self._rows(matches)
        self.repository.sync_global_recommendations(recommendation_date or date.today().isoformat(), rows)
        return len(rows)

    @staticmethod
    def _rows(matches) -> list[dict]:
        return [
            {"job_id": item.job_id, "recommend_reason": item.match.recommend_reason}
            for item in matches
            if item.match.should_push
        ]
