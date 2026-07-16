from pathlib import Path

from openpyxl import load_workbook

from jobpicky.exporters import build_feishu_record, export_jobs_to_excel
from jobpicky.models import Job
from jobpicky.services.scanning import run_daily_with_jobs
from jobpicky.storage import JobRepository



def test_alljobs_export_hides_matching_debug_fields(tmp_path: Path):
    output = tmp_path / "all_jobs.xlsx"
    row = {
        "id": 1,
        "source": "WonderCV",
        "company": "TargetCo",
        "clean_title": "FPGA engineer",
        "summary": "campus role",
        "batch": "fall",
        "target_graduate_year": "2027",
        "degree": "bachelor",
        "city": "Shanghai",
        "collected_date": "2026-07-03",
        "deadline": "2026-08-01",
        "industry": "semiconductor",
        "company_type": "listed",
        "job_tags": "hardware",
        "special_marks": "referral",
        "detail_url": "https://example.com/detail",
        "apply_url": "https://example.com/apply",
        "first_seen": "2026-07-03T08:00:00",
        "last_seen": "2026-07-03T08:00:00",
        "verify_status": "pending",
        "user_status": "unread",
        "note": "",
        "priority": "push",
        "match_score": 90,
        "matched_keywords": "FPGA",
        "match_config_version": "7",
        "matched_at": "2026-07-03T08:01:00",
    }

    record = build_feishu_record(row)
    export_jobs_to_excel([row], output)

    headers = [cell.value for cell in load_workbook(output).active[1]]
    assert "优先级" not in headers
    assert "匹配分数" not in headers
    assert "命中关键词" not in headers
    assert "匹配配置版本" not in headers
    assert "最近匹配时间" not in headers
    assert "公司" in headers
    assert "优先级" not in record["fields"]
    assert "匹配分数" not in record["fields"]


def test_repository_lists_daily_new_jobs_by_collected_date(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:today",
            company="TodayCo",
            title="today job",
            first_seen="2026-07-03T08:00:00",
            collected_date="2026-07-02",
        )
    )
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:yesterday",
            company="OldCo",
            title="old job",
            first_seen="2026-07-02T08:00:00",
            collected_date="2026-07-03",
        )
    )

    rows = repo.list_daily_new_jobs("2026-07-03")

    assert [row["company"] for row in rows] == ["OldCo"]
    assert set(rows[0]) >= {"job_id", "company", "title", "user_status", "note"}
    assert "match_score" not in rows[0]


def test_daily_pipeline_appends_only_push_recommendations_idempotently(tmp_path: Path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    jobs = [
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:push",
            company="TargetCo",
            title="2027届校园招聘",
            batch="秋招",
            target_graduate_year="2027届",
            city="Shanghai",
            collected_date="2026-07-03",
        ),
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:skip",
            company="OtherCo",
            title="2027届校园招聘",
            batch="秋招",
            target_graduate_year="2027届",
            city="Shanghai",
            collected_date="2026-07-03",
        ),
    ]

    summary = run_daily_with_jobs(repo, jobs, mock_config(), run_date="2026-07-03")
    run_daily_with_jobs(repo, jobs, mock_config(), run_date="2026-07-03")

    recommended = repo.list_recommended_jobs("2026-07-03")
    assert summary.items_seen == 2
    assert summary.new_items == 2
    assert summary.updated_items == 0
    assert summary.recommended_items == 1
    assert [row["company"] for row in recommended] == ["TargetCo"]
    assert recommended[0]["recommend_reason"] == "命中必看公司"


def test_alljobs_rows_include_recommendation_fields_for_feishu_views(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    inserted = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:recommended",
            company="TargetCo",
            title="FPGA engineer",
            first_seen="2026-07-03T08:00:00",
            collected_date="2026-07-03",
        )
    )
    repo.append_recommendations("2026-07-03", [{"job_id": inserted.job_id, "recommend_reason": "命中岗位方向"}])

    row = repo.list_all_jobs()[0]
    record = build_feishu_record(row)

    assert row["recommendation_status"] == "推荐"
    assert row["recommendation_date"] == "2026-07-03"
    assert row["recommend_reason"] == "命中岗位方向"
    assert record["fields"]["推荐状态"] == "推荐"
    assert record["fields"]["收录日期"] == 1783008000000
