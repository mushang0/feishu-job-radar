from dataclasses import dataclass
from datetime import date
from typing import Callable

from .matcher import Matcher
from .models import Job
from .storage import JobRepository
from .core.ingestion import JobIngestionService
from .core.matching import MatchingService
from .core.recommendations import RecommendationService
from .wondercv import merge_detail_into_job, parse_wondercv_detail
from .audit import recover_user_states


@dataclass(frozen=True, slots=True)
class DailySummary:
    items_seen: int
    new_items: int
    updated_items: int
    relevant_items: int
    recommended_items: int = 0
    matched_items: int = 0


@dataclass(frozen=True, slots=True)
class InitSummary:
    pages_scanned: int
    items_seen: int
    new_items: int
    updated_items: int
    relevant_items: int
    recommended_items: int = 0


def backfill_existing_job_details(
    repo: JobRepository,
    crawler,
    config: dict,
    recommendation_date: str | None = None,
    min_raw_text_length: int = 500,
) -> DailySummary:
    matcher = Matcher(config)
    rows = repo.list_stored_jobs()
    candidates = [
        row
        for row in rows
        if row.get("detail_url")
        and (
            row.get("parse_status") != "detail_ready"
            or not row.get("content_hash")
            or len(row.get("raw_text") or "") < min_raw_text_length
        )
    ]
    recommendations: list[dict] = []
    relevant_items = 0
    target_date = recommendation_date or date.today().isoformat()

    for row in candidates:
        job = _job_from_row(row)
        # Existing detail text can be safely re-analysed without another
        # network request.  Short list-card text still goes through the crawler.
        if len(job.raw_text or "") >= min_raw_text_length:
            detail = parse_wondercv_detail(job.raw_text or "")
            enriched = merge_detail_into_job(job, detail) if detail.raw_text else crawler.enrich_detail(job)
        else:
            enriched = crawler.enrich_detail(job)
        result = repo.upsert_job(enriched)
        match = matcher.match(enriched)
        repo.save_match(result.job_id, match)
        if match.is_relevant:
            relevant_items += 1
        if match.should_push:
            recommendations.append({"job_id": result.job_id, "recommend_reason": match.recommend_reason})

    repo.append_recommendations(target_date, recommendations)
    return DailySummary(
        items_seen=len(candidates),
        new_items=0,
        updated_items=len(candidates),
        relevant_items=relevant_items,
        recommended_items=len(recommendations),
    )


def enrich_official_urls(
    repo: JobRepository,
    finder,
    *,
    only_recommended: bool = True,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> DailySummary:
    rows = repo.list_recommended_jobs() if only_recommended else repo.list_all_jobs()
    candidates = [row for row in rows if not row.get("official_url")]
    if limit is not None:
        candidates = candidates[: max(limit, 0)]
    updated_items = 0
    for row in candidates:
        company = str(row.get("company") or "该公司").strip()
        if progress:
            progress(f"正在查找「{company}」的官方投递入口")
        job = _job_from_row(row)
        job_id = int(row.get("job_id") or row.get("id"))
        official_url = finder.find_best(job)
        if official_url and repo.update_official_url_if_empty(job_id, official_url):
            updated_items += 1
            if progress:
                progress(f"已整理「{company}」的官方投递入口")
    return DailySummary(
        items_seen=len(candidates),
        new_items=0,
        updated_items=updated_items,
        relevant_items=0,
        recommended_items=0,
    )


def run_init_with_page_batches(
    repo: JobRepository,
    page_batches,
    config: dict,
    run_date: str | None = None,
) -> InitSummary:
    pages_scanned = 0
    items_seen = 0
    new_items = 0
    updated_items = 0
    relevant_items = 0
    all_matches = []

    for jobs in page_batches:
        pages_scanned += 1
        items_seen += len(jobs)
        ingestion = JobIngestionService(repo, config).ingest(jobs)
        matching = MatchingService(repo, config).match_ingested(ingestion.changed_items)
        new_items += ingestion.new_items
        updated_items += ingestion.updated_items
        relevant_items += matching.relevant_items
        all_matches.extend(matching.matches)

    recommended_items = RecommendationService(repo).rebuild_all(all_matches, run_date)

    return InitSummary(
        pages_scanned=pages_scanned,
        items_seen=items_seen,
        new_items=new_items,
        updated_items=updated_items,
        relevant_items=relevant_items,
        recommended_items=recommended_items,
    )


def _job_from_row(row: dict) -> Job:
    return JobRepository.job_from_row(row)
def pull_user_states_from_feishu(repo: JobRepository, client: "FeishuBitableClient"):
    """Pull user-owned fields and return the complete, auditable result."""
    return recover_user_states(repo, client.list_all_records())
