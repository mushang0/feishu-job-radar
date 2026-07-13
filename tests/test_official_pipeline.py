from pathlib import Path

from jobpicky.models import Job, MatchResult
from jobpicky.pipeline import enrich_official_urls
from jobpicky.storage import JobRepository


def _push_match() -> MatchResult:
    return MatchResult(
        matched_keywords=[],
        matched_strong_keywords=[],
        matched_weak_keywords=[],
        matched_industry_keywords=[],
        matched_company_rule="",
        matched_city_rule="",
        negative_keywords=[],
        match_score=100,
        priority="push",
        is_relevant=True,
        should_push=True,
        needs_verify=False,
        match_reason="推荐",
        verify_status="未核验",
        suggested_search_terms=[],
        match_config_version="",
        matched_at="2026-07-09T00:00:00",
        recommend_reason="推荐",
    )


class Finder:
    def __init__(self):
        self.calls = []

    def find_best(self, job: Job) -> str:
        self.calls.append(job.company)
        return f"https://official.example.com/{job.company}"


def test_enrich_official_urls_only_fills_recommended_empty_jobs(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    first = repo.upsert_job(Job(dedupe_key="one", company="TargetCo", title="工程师"))
    second = repo.upsert_job(Job(dedupe_key="two", company="ManualCo", title="工程师", official_url="https://manual.example.com"))
    third = repo.upsert_job(Job(dedupe_key="three", company="SkipCo", title="工程师"))
    repo.save_match(first.job_id, _push_match())
    repo.save_match(second.job_id, _push_match())
    repo.append_recommendations("2026-07-09", [{"job_id": first.job_id, "recommend_reason": "推荐"}])
    repo.append_recommendations("2026-07-09", [{"job_id": second.job_id, "recommend_reason": "推荐"}])

    finder = Finder()
    summary = enrich_official_urls(repo, finder, only_recommended=True)
    rows = {row["company"]: row for row in repo.list_all_jobs()}

    assert summary.items_seen == 1
    assert summary.updated_items == 1
    assert finder.calls == ["TargetCo"]
    assert rows["TargetCo"]["official_url"] == "https://official.example.com/TargetCo"
    assert rows["ManualCo"]["official_url"] == "https://manual.example.com"
    assert rows["SkipCo"]["official_url"] is None
    assert rows["TargetCo"]["sync_status"] == "pending"
