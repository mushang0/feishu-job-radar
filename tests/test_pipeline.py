from pathlib import Path

from jobpicky.models import Job
from jobpicky.pipeline import backfill_existing_job_details
from jobpicky.services.scanning import run_daily_with_jobs
from jobpicky.services.local import rematch_local
from jobpicky.storage import JobRepository


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

    _repo, summary = rematch_local(repo.db_path, mock_config(), recommendation_date="2026-07-04")

    recommended = repo.list_recommended_jobs("2026-07-04")
    assert summary.items_seen == 1
    assert summary.recommended_items == 1
    assert recommended[0]["company"] == "HistoryCo"
    assert recommended[0]["recommend_reason"] == "命中岗位方向：硬件/嵌入式"


def test_pipeline_pulls_from_feishu(tmp_path: Path):
    from unittest.mock import Mock
    from jobpicky.pipeline import pull_user_states_from_feishu

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
    repo.mark_sync(inserted.job_id, "synced", record_id="rec-123")

    mock_client = Mock()
    mock_client.list_all_records.return_value = [
        {
            "record_id": "rec-123",
                "fields": {
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


def test_daily_pipeline_stores_detail_failure_without_recommendation(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(
        source="WonderCV",
        dedupe_key="WonderCV:id:detail-failed",
        company="OtherCo",
        title="2027届 FPGA 工程师",
        batch="秋招",
        target_graduate_year="2027届",
        parse_status="detail_failed",
    )

    summary = run_daily_with_jobs(repo, [job], mock_config(), run_date="2026-07-03")

    assert summary.new_items == 1
    assert summary.recommended_items == 0
    assert repo.list_recommended_jobs("2026-07-03") == []


def test_daily_pipeline_rematches_existing_job_when_visible_fields_change(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    first = Job(
        source="WonderCV",
        dedupe_key="WonderCV:id:changed",
        company="OtherCo",
        title="2027届校园招聘公告",
        batch="秋招",
        target_graduate_year="2027届",
    )
    repo_result = run_daily_with_jobs(repo, [first], mock_config(), run_date="2026-07-03")
    assert repo_result.recommended_items == 0

    updated = Job(
        source="WonderCV",
        dedupe_key="WonderCV:id:changed",
        company="OtherCo",
        title="2027届 FPGA 工程师",
        batch="秋招",
        target_graduate_year="2027届",
    )
    summary = run_daily_with_jobs(repo, [updated], mock_config(), run_date="2026-07-04")

    assert summary.updated_items == 1
    assert summary.recommended_items == 1
    assert [row["company"] for row in repo.list_recommended_jobs("2026-07-04")] == ["OtherCo"]


def test_daily_pipeline_does_not_count_unchanged_duplicate_as_updated(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(
        source="WonderCV",
        dedupe_key="WonderCV:id:unchanged",
        company="OtherCo",
        title="2027届 FPGA 工程师",
        batch="秋招",
        target_graduate_year="2027届",
        content_hash="same",
    )

    first = run_daily_with_jobs(repo, [job], mock_config(), run_date="2026-07-03")
    second = run_daily_with_jobs(repo, [job], mock_config(), run_date="2026-07-04")

    assert first.new_items == 1
    assert second.new_items == 0
    assert second.updated_items == 0
    assert second.matched_items == 0
    assert repo.count_jobs() == 1


def test_preserved_official_url_does_not_make_an_unchanged_job_look_updated(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(dedupe_key="WonderCV:id:official", company="OtherCo", title="普通岗位")
    inserted = repo.upsert_job(job)
    repo.update_official_url_if_empty(inserted.job_id, "https://careers.example.com/job")

    summary = run_daily_with_jobs(repo, [job], mock_config(), run_date="2026-07-04")

    assert summary.updated_items == 0
    assert repo.list_all_jobs()[0]["official_url"] == "https://careers.example.com/job"


def test_daily_pipeline_rematches_when_detail_content_changes(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    first = Job(
        dedupe_key="WonderCV:id:detail-change",
        company="OtherCo",
        title="2027届校园招聘公告",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="普通岗位",
        role_text="普通岗位",
        content_hash="v1",
    )
    run_daily_with_jobs(repo, [first], mock_config(), run_date="2026-07-03")
    changed = Job(
        dedupe_key="WonderCV:id:detail-change",
        company="OtherCo",
        title="2027届校园招聘公告",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="FPGA 硬件岗位",
        role_text="FPGA 硬件岗位",
        content_hash="v2",
    )

    summary = run_daily_with_jobs(repo, [changed], mock_config(), run_date="2026-07-04")

    assert summary.updated_items == 1
    assert summary.matched_items == 1
    assert summary.recommended_items == 1

