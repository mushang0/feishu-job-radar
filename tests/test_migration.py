from pathlib import Path

from job_monitor.migration import build_migration_plan
from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_migration_dry_run_reports_actions_without_mutating_records(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = repo.upsert_job(Job(dedupe_key="job:1", company="Example", title="Engineer"))
    records = [
        {"record_id": "rec-1", "fields": {"岗位ID": str(job.job_id), "用户状态": "已收藏"}},
        {"record_id": "rec-x", "fields": {"岗位ID": "999", "用户状态": "未看"}},
    ]

    plan = build_migration_plan(repo, records)

    assert [(item.record_id, item.action, item.status) for item in plan.items] == [
        ("rec-1", "保留", "收藏"),
        ("rec-x", "隔离", "待处理"),
    ]
