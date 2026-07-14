from dataclasses import dataclass

from ..matcher import Matcher
from ..models import Job, MatchResult
from ..storage import JobRepository


@dataclass(frozen=True, slots=True)
class MatchedJob:
    job_id: int
    match: MatchResult


@dataclass(frozen=True, slots=True)
class MatchingSummary:
    matched_items: int
    relevant_items: int
    matches: tuple[MatchedJob, ...]


class MatchingService:
    def __init__(self, repository: JobRepository, config: dict):
        self.repository = repository
        self.matcher = Matcher(config)

    def match_ingested(self, items) -> MatchingSummary:
        return self._match((item.job_id, item.job) for item in items if item.job.parse_status == "detail_ready")

    def match_job_ids(self, job_ids) -> MatchingSummary:
        pairs = []
        for job_id in job_ids:
            row = self.repository.get_stored_job(int(job_id))
            if row and row.get("parse_status") == "detail_ready":
                pairs.append((int(job_id), self.repository.job_from_row(row)))
        return self._match(pairs)

    def rematch_all(self) -> MatchingSummary:
        pairs = (
            (int(row["id"]), self.repository.job_from_row(row))
            for row in self.repository.list_stored_jobs()
            if row.get("parse_status") == "detail_ready"
        )
        return self._match(pairs)

    def _match(self, pairs) -> MatchingSummary:
        matches = []
        for job_id, job in pairs:
            match = self.matcher.match(job)
            self.repository.save_match(job_id, match)
            matches.append(MatchedJob(job_id, match))
        return MatchingSummary(
            matched_items=len(matches),
            relevant_items=sum(item.match.is_relevant for item in matches),
            matches=tuple(matches),
        )
