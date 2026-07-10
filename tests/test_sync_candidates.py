from pathlib import Path

from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_feishu_sync_candidates_include_recommendations_and_tracked_jobs_only(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    recommended = repo.upsert_job(Job(dedupe_key="job:recommended", company="A", title="Engineer")).job_id
    tracked = repo.upsert_job(Job(dedupe_key="job:tracked", company="B", title="Engineer")).job_id
    ignored = repo.upsert_job(Job(dedupe_key="job:ignored", company="C", title="Engineer")).job_id
    repo.append_recommendations("2026-07-10", [{"job_id": recommended, "recommend_reason": "匹配岗位方向"}])
    repo.update_user_state(tracked, "收藏", "keep")
    repo.update_user_state(ignored, "不合适", "hide")

    assert {row["job_id"] for row in repo.list_feishu_sync_candidates()} == {recommended, tracked}
