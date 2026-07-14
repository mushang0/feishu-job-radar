from dataclasses import dataclass, replace

from ..models import Job
from ..normalizer import build_dedupe_key, normalize_company
from ..storage import JobRepository


@dataclass(frozen=True, slots=True)
class IngestedJob:
    job_id: int
    job: Job
    created: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    items_seen: int
    new_items: int
    updated_items: int
    items: tuple[IngestedJob, ...]

    @property
    def changed_items(self) -> tuple[IngestedJob, ...]:
        return tuple(item for item in self.items if item.created or item.changed)


class JobIngestionService:
    def __init__(self, repository: JobRepository, config: dict | None = None):
        self.repository = repository
        self.aliases = (config or {}).get("system_taxonomy", {}).get("company_aliases", {})

    def ingest(self, jobs) -> IngestionSummary:
        items = []
        for source_job in jobs:
            job = self._normalize(source_job)
            result = self.repository.upsert_job(job)
            items.append(IngestedJob(result.job_id, job, result.created, result.changed))
        return IngestionSummary(
            items_seen=len(items),
            new_items=sum(item.created for item in items),
            updated_items=sum(item.changed and not item.created for item in items),
            items=tuple(items),
        )

    def _normalize(self, job: Job) -> Job:
        company_normalized = job.company_normalized or normalize_company(job.company, self.aliases)
        dedupe_key = job.dedupe_key or build_dedupe_key(
            source=job.source,
            source_job_id=job.source_job_id,
            detail_url=job.detail_url,
            company_normalized=company_normalized,
            title=job.clean_title or job.title,
            batch=job.batch,
            collected_date=job.collected_date,
        )
        return replace(job, company_normalized=company_normalized, dedupe_key=dedupe_key)
