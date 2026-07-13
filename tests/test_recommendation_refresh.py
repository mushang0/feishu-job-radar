from pathlib import Path

from jobpicky.models import Job
from jobpicky.pipeline import rematch_existing_jobs
from jobpicky.storage import JobRepository


def test_rematch_replaces_recommendations_for_target_date(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    old = repo.upsert_job(Job(dedupe_key="WonderCV:id:old", company="OldCo", title="2027 old notice", batch="fall", target_graduate_year="2027"))
    current = repo.upsert_job(Job(dedupe_key="WonderCV:id:current", company="CurrentCo", title="2027 fall FPGA", batch="fall", target_graduate_year="2027"))
    repo.append_recommendations("2026-07-04", [{"job_id": old.job_id, "recommend_reason": "stale"}])

    config = {
        "user_profile": {
            "graduate_years": ["2027"],
            "batches": ["fall"],
            "role_groups": ["hardware"],
            "target_industries": [],
            "target_cities": [],
            "must_watch_companies": [],
            "exclude_role_groups": [],
        },
        "system_taxonomy": {
            "role_groups": {"hardware": ["FPGA"]},
            "exclude_role_groups": {},
            "generic_role_terms": [],
            "important_company_types": [],
            "important_company_marks": [],
            "company_aliases": {},
        },
    }

    rematch_existing_jobs(repo, config, recommendation_date="2026-07-04")

    rows = repo.list_recommended_jobs("2026-07-04")
    assert [row["job_id"] for row in rows] == [current.job_id]
