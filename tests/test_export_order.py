from pathlib import Path

from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_list_jobs_with_matches_orders_by_collected_date_newest_first(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:old",
            company="OldCo",
            title="old job",
            collected_date="2026-06-20",
        )
    )
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:new",
            company="NewCo",
            title="new job",
            collected_date="2026-07-02",
        )
    )

    rows = repo.list_jobs_with_matches()

    assert [row["company"] for row in rows] == ["NewCo", "OldCo"]
