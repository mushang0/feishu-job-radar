from pathlib import Path

from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_repository_upserts_new_job_and_does_not_duplicate(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(
        source="WonderCV",
        source_job_id="abc",
        dedupe_key="WonderCV:id:abc",
        company="示例公司",
        company_normalized="示例公司",
        title="2027校园招聘",
    )

    first = repo.upsert_job(job)
    second = repo.upsert_job(job)

    assert first.created is True
    assert second.created is False
    assert repo.count_jobs() == 1


def test_repository_saves_match_result(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    inserted = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:abc",
            company="示例公司",
            title="FPGA工程师",
        )
    )

    repo.save_match(
        inserted.job_id,
        {
            "matched_keywords": ["FPGA"],
            "matched_company_rule": "",
            "matched_city_rule": "",
            "negative_keywords": [],
            "match_score": 80,
            "priority": "push",
            "is_relevant": True,
            "should_push": True,
            "match_reason": "命中岗位方向：硬件/嵌入式",
            "verify_status": "未核验",
            "suggested_search_terms": [],
        },
    )

    saved = repo.get_job_with_match(inserted.job_id)
    assert saved["priority"] == "push"
    assert saved["matched_keywords"] == "FPGA"


def test_repository_updates_user_state(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    inserted = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:abc",
            company="测试公司",
            title="软件研发",
        )
    )

    repo.update_user_state(inserted.job_id, "已收藏", "测试备注")

    saved = repo.get_job_with_match(inserted.job_id)
    assert saved["user_status"] == "已收藏"
    assert saved["note"] == "测试备注"


def test_repository_does_not_implicitly_copy_seed_if_missing(tmp_path: Path):
    seed_file = tmp_path / "jobs_seed.sqlite"
    seed_file.write_text("dummy database content", encoding="utf-8")

    db_file = tmp_path / "jobs.sqlite"
    assert not db_file.exists()

    # Seed restoration is an explicit init/reset concern, not a repository side effect.
    repo = JobRepository(db_file)

    assert repo.db_path == db_file
    assert not db_file.exists()

