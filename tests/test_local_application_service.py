from pathlib import Path

from jobpicky.core import DailyUpdateService
from jobpicky.models import Job
from jobpicky.services import scanning
from jobpicky.services.local import LocalApplicationService
from jobpicky.storage import JobRepository


def test_initialize_and_update_bootstraps_rematches_recommends_and_runs_daily_once(
    monkeypatch, tmp_path: Path
):
    config = {
        "user_profile": {
            "graduate_years": ["2027届"],
            "batches": ["秋招"],
            "role_groups": ["硬件/嵌入式"],
            "target_cities": [],
            "must_watch_companies": [],
            "exclude_role_groups": [],
        },
        "system_taxonomy": {
            "role_groups": {"硬件/嵌入式": ["FPGA"]},
            "exclude_role_groups": {},
            "generic_role_terms": [],
            "important_company_types": [],
            "important_company_marks": [],
            "company_aliases": {},
        },
    }
    daily_runs = 0
    original_run = DailyUpdateService.run

    def counted_run(service, recommendation_date=None):
        nonlocal daily_runs
        daily_runs += 1
        return original_run(service, recommendation_date)

    class LocalCrawler:
        def __init__(self, _config, cancel_check=None):
            self.cancel_check = cancel_check

        def crawl(self, mode, should_stop):
            assert mode == "daily"
            assert self.cancel_check is not None
            job = Job(
                source_job_id="local-integration-daily",
                dedupe_key="local-integration-daily",
                company="Example",
                title="2027届 FPGA 工程师",
                batch="秋招",
                target_graduate_year="2027届",
            )
            return type(
                "Crawl",
                (),
                {
                    "jobs": [job],
                    "pages_scanned": 1,
                    "error": None,
                    "interrupted": False,
                    "sources_attempted": 1,
                    "sources_succeeded": 1,
                    "sources_failed": 0,
                },
            )()

    monkeypatch.setattr(scanning, "WonderCVCrawler", LocalCrawler)
    monkeypatch.setattr(DailyUpdateService, "run", counted_run)
    database = tmp_path / "profile" / "jobs.sqlite"

    result = LocalApplicationService(database, config).initialize_and_update(task_id="local-test")

    repo = JobRepository(database)
    stored = repo.list_stored_jobs()
    daily_job = next(row for row in stored if row["dedupe_key"] == "local-integration-daily")
    recommendations = repo.list_recommended_jobs()
    assert database.is_file()
    assert result.seeded is True
    assert 0 < result.baseline_items <= 747
    assert result.baseline_recommended_items > 0
    assert result.daily.status == "success"
    assert result.daily.created_count == 1
    assert daily_runs == 1
    assert len(stored) == 748
    assert daily_job["title"] == "2027届 FPGA 工程师"
    assert any(row["job_id"] == daily_job["id"] for row in recommendations)
