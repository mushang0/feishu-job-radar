from pathlib import Path

from job_monitor.models import Job
from job_monitor.pipeline import backfill_existing_job_details
from job_monitor.storage import JobRepository


def test_backfill_details_enriches_short_historical_job_and_recommends(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(
        source="WonderCV",
        source_job_id="dji-11264",
        detail_url="https://www.wondercv.com/xiaozhao/dji-11264/",
        dedupe_key="WonderCV:id:dji-11264",
        company="深圳市大疆创新科技有限公司",
        title="大疆27秋招",
        raw_text="大疆27秋招 技术岗",
        batch="秋招",
        target_graduate_year="2027届",
    )
    repo.upsert_job(job)

    class Crawler:
        def enrich_detail(self, job: Job) -> Job:
            job.raw_text = "招聘岗位：嵌入式工程师、GNSS定位算法工程师、测试开发工程师。"
            job.job_tags = ["嵌入式", "GNSS", "测试开发"]
            job.content_hash = "hash"
            return job

    config = {
        "profile": {"version": 1},
        "user_profile": {
            "graduate_years": ["2027届"],
            "batches": ["秋招"],
            "role_groups": ["硬件/嵌入式"],
            "target_industries": [],
            "target_cities": [],
            "must_watch_companies": [],
            "exclude_role_groups": [],
            "daily_push_limit": 20,
        },
        "system_taxonomy": {
            "role_groups": {"硬件/嵌入式": ["嵌入式", "GNSS", "测试开发"]},
            "exclude_role_groups": {},
            "generic_role_terms": [],
            "important_company_types": [],
            "important_company_marks": [],
            "company_aliases": {},
        },
    }

    summary = backfill_existing_job_details(repo, Crawler(), config, recommendation_date="2026-07-03")

    recommended = repo.list_recommended_jobs("2026-07-03")
    stored = repo.list_stored_jobs()[0]
    assert summary.items_seen == 1
    assert summary.updated_items == 1
    assert summary.recommended_items == 1
    assert stored["content_hash"] == "hash"
    assert "嵌入式" in stored["job_tags"]
    assert recommended[0]["company"] == "深圳市大疆创新科技有限公司"
