from pathlib import Path

from job_monitor.models import Job
from job_monitor.pipeline import backfill_existing_job_details, rematch_existing_jobs, run_daily_with_jobs
from job_monitor.storage import JobRepository


def test_daily_pipeline_stores_all_jobs_but_recommends_only_push_jobs(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    jobs = [
        Job(source="WonderCV", dedupe_key="WonderCV:id:push", company="TargetCo", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届"),
        Job(source="WonderCV", dedupe_key="WonderCV:id:skip", company="OtherCo", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届"),
    ]

    summary = run_daily_with_jobs(repo, jobs, mock_config(), run_date="2026-07-03")
    run_daily_with_jobs(repo, jobs, mock_config(), run_date="2026-07-03")

    recommended = repo.list_recommended_jobs("2026-07-03")
    assert summary.items_seen == 2
    assert summary.new_items == 2
    assert summary.updated_items == 0
    assert summary.recommended_items == 1
    assert repo.count_jobs() == 2
    assert [row["company"] for row in recommended] == ["TargetCo"]
    assert recommended[0]["recommend_reason"] == "命中必看公司"


def test_daily_push_limit_does_not_limit_recommendation_storage(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    jobs = [
        Job(source="WonderCV", dedupe_key=f"WonderCV:id:{index}", company=f"Co{index}", title="2027届FPGA工程师", batch="秋招", target_graduate_year="2027届")
        for index in range(3)
    ]

    summary = run_daily_with_jobs(repo, jobs, mock_config(daily_push_limit=1), run_date="2026-07-03")

    assert summary.new_items == 3
    assert summary.recommended_items == 3
    assert repo.count_jobs() == 3
    assert len(repo.list_recommended_jobs("2026-07-03")) == 3


def test_rematch_existing_jobs_backfills_new_recommendations(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(source="WonderCV", dedupe_key="WonderCV:id:history", company="HistoryCo", title="2027届FPGA工程师", batch="秋招", target_graduate_year="2027届")
    repo.upsert_job(job)

    summary = rematch_existing_jobs(repo, mock_config(), recommendation_date="2026-07-04")

    recommended = repo.list_recommended_jobs("2026-07-04")
    assert summary.items_seen == 1
    assert summary.recommended_items == 1
    assert recommended[0]["company"] == "HistoryCo"
    assert recommended[0]["recommend_reason"] == "命中岗位方向：硬件/嵌入式"


def test_pipeline_pulls_from_feishu(tmp_path: Path):
    from unittest.mock import Mock
    from job_monitor.pipeline import pull_user_states_from_feishu

    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    inserted = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:123",
            company="测试公司",
            title="软件研发",
        )
    )

    mock_client = Mock()
    mock_client.list_all_records.return_value = [
        {
            "record_id": "rec-123",
                "fields": {
                    "岗位ID": str(inserted.job_id),
                    "求职状态": "收藏",
                    "备注": [{"text": "希望很大"}]  # 支持段结构
                }
        }
    ]

    result = pull_user_states_from_feishu(repo, mock_client)
    assert result.updated_count == 1

    saved = repo.list_all_jobs()[0]
    assert saved["user_status"] == "收藏"
    assert saved["note"] == "希望很大"
    assert saved["feishu_record_id"] == "rec-123"

