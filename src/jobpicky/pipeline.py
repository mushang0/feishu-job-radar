from dataclasses import dataclass
from datetime import date

from .matcher import Matcher
from .models import Job
from .storage import JobRepository
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


def run_daily_with_jobs(repo: JobRepository, jobs: list[Job], config: dict, run_date: str | None = None) -> DailySummary:
    matcher = Matcher(config)
    new_items = 0
    updated_items = 0
    relevant_items = 0
    recommendations: list[dict] = []
    matched_items = 0
    recommendation_date = run_date or date.today().isoformat()

    for job in jobs:
        result = repo.upsert_job(job)
        if result.created:
            new_items += 1
        elif result.changed:
            updated_items += 1
        # List-page candidates are stored for retry, but never become ordinary
        # recommendations until the detail extractor has produced role evidence.
        if job.parse_status == "detail_ready" and (result.created or result.changed):
            matched_items += 1
            match = matcher.match(job)
            repo.save_match(result.job_id, match)
            if match.is_relevant:
                relevant_items += 1
            if match.should_push:
                recommendations.append({"job_id": result.job_id, "recommend_reason": match.recommend_reason})

    repo.append_recommendations(recommendation_date, recommendations)
    return DailySummary(
        items_seen=len(jobs),
        new_items=new_items,
        updated_items=updated_items,
        relevant_items=relevant_items,
        recommended_items=len(recommendations),
        matched_items=matched_items,
    )


def rematch_existing_jobs(repo: JobRepository, config: dict, recommendation_date: str | None = None) -> DailySummary:
    matcher = Matcher(config)
    rows = repo.list_stored_jobs()
    recommendations: list[dict] = []
    relevant_items = 0
    target_date = recommendation_date or date.today().isoformat()

    for row in rows:
        job = _job_from_row(row)
        match = matcher.match(job)
        repo.save_match(int(row["id"]), match)
        if match.is_relevant:
            relevant_items += 1
        if match.should_push:
            recommendations.append({"job_id": int(row["id"]), "recommend_reason": match.recommend_reason})

    repo.sync_global_recommendations(target_date, recommendations)
    return DailySummary(
        items_seen=len(rows),
        new_items=0,
        updated_items=len(rows),
        relevant_items=relevant_items,
        recommended_items=len(recommendations),
    )


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
) -> DailySummary:
    rows = repo.list_recommended_jobs() if only_recommended else repo.list_all_jobs()
    candidates = [row for row in rows if not row.get("official_url")]
    if limit is not None:
        candidates = candidates[: max(limit, 0)]
    updated_items = 0
    for row in candidates:
        job = _job_from_row(row)
        job_id = int(row.get("job_id") or row.get("id"))
        official_url = finder.find_best(job)
        if official_url and repo.update_official_url_if_empty(job_id, official_url):
            updated_items += 1
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
    matcher = Matcher(config)
    pages_scanned = 0
    items_seen = 0
    new_items = 0
    updated_items = 0
    relevant_items = 0
    recommendations: dict[int, dict] = {}

    for jobs in page_batches:
        pages_scanned += 1
        items_seen += len(jobs)
        for job in jobs:
            result = repo.upsert_job(job)
            if result.created:
                new_items += 1
            else:
                updated_items += 1
            match = matcher.match(job)
            repo.save_match(result.job_id, match)
            if match.is_relevant:
                relevant_items += 1
            if match.should_push:
                recommendations[result.job_id] = {"job_id": result.job_id, "recommend_reason": match.recommend_reason}

    repo.sync_global_recommendations(run_date or date.today().isoformat(), recommendations.values())

    return InitSummary(
        pages_scanned=pages_scanned,
        items_seen=items_seen,
        new_items=new_items,
        updated_items=updated_items,
        relevant_items=relevant_items,
        recommended_items=len(recommendations),
    )


def _job_from_row(row: dict) -> Job:
    return Job(
        source=row.get("source") or "WonderCV",
        source_job_id=row.get("source_job_id"),
        source_url=row.get("source_url"),
        detail_url=row.get("detail_url"),
        dedupe_key=row.get("dedupe_key"),
        company=row.get("company") or "",
        raw_company=row.get("raw_company"),
        company_normalized=row.get("company_normalized"),
        title=row.get("title") or "",
        raw_title=row.get("raw_title"),
        clean_title=row.get("clean_title"),
        summary=row.get("summary"),
        batch=row.get("batch"),
        target_graduate_year=row.get("target_graduate_year"),
        degree=row.get("degree"),
        city=row.get("city"),
        location_text=row.get("location_text"),
        collected_date=row.get("collected_date"),
        deadline=row.get("deadline"),
        company_type=row.get("company_type"),
        industry=row.get("industry"),
        tags=_split(row.get("tags")),
        job_tags=_split(row.get("job_tags")),
        special_marks=_split(row.get("special_marks")),
        raw_tags=_split(row.get("raw_tags")),
        raw_text=row.get("raw_text"),
        role_text=row.get("role_text"),
        announcement_text=row.get("announcement_text"),
        role_signals=_split(row.get("role_signals")),
        field_evidence=row.get("field_evidence"),
        extraction_version=row.get("extraction_version"),
        apply_url=row.get("apply_url"),
        official_url=row.get("official_url"),
        parse_status=row.get("parse_status") or "ok",
        parse_note=row.get("parse_note"),
        first_seen=row.get("first_seen"),
        last_seen=row.get("last_seen"),
        last_checked=row.get("last_checked"),
        content_hash=row.get("content_hash"),
        is_active=int(row.get("is_active") if row.get("is_active") is not None else 1),
    )


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part for part in str(value).split(";") if part]


def pull_user_states_from_feishu(repo: JobRepository, client: "FeishuBitableClient"):
    """Pull user-owned fields and return the complete, auditable result."""
    return recover_user_states(repo, client.list_all_records())
