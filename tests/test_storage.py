import sqlite3
from pathlib import Path

import pytest

from jobpicky.models import Job
from jobpicky.storage import JobRepository


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


def test_city_filter_keeps_jobs_whose_location_is_pending(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    repo.upsert_job(Job(dedupe_key="pending:1", company="待确认公司", title="嵌入式工程师", city=None))
    repo.upsert_job(Job(dedupe_key="known:1", company="上海公司", title="嵌入式工程师", city="上海市"))

    rows, total = repo.search_jobs(city="深圳市")

    assert total == 1
    assert [row["company"] for row in rows] == ["待确认公司"]
    assert rows[0]["location_status"] == "pending"


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


def _make_old_schema_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                dedupe_key TEXT UNIQUE NOT NULL,
                company TEXT,
                title TEXT
            );
            CREATE TABLE job_user_state (job_id INTEGER UNIQUE, status TEXT, note TEXT);
            CREATE TABLE scan_runs (
                id INTEGER PRIMARY KEY,
                run_type TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                status TEXT,
                pages_scanned INTEGER,
                items_seen INTEGER,
                new_items INTEGER,
                updated_items INTEGER,
                error_message TEXT
            );
            INSERT INTO jobs(id, dedupe_key, company, title)
                VALUES (7, 'legacy:7', 'Legacy Co', 'Legacy Job');
            INSERT INTO scan_runs(id, run_type, status, error_message)
                VALUES (3, 'daily', 'success', 'legacy record');
            """
        )


def test_repository_migrates_old_schema_preserves_data_and_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "old.sqlite"
    _make_old_schema_database(db_path)
    repo = JobRepository(db_path)

    repo.init_schema()
    repo.init_schema()

    with sqlite3.connect(db_path) as conn:
        scan_columns = {row[1] for row in conn.execute("PRAGMA table_info(scan_runs)")}
        job = conn.execute("SELECT company, title FROM jobs WHERE id = 7").fetchone()
        old_run = conn.execute("SELECT status, error_message FROM scan_runs WHERE id = 3").fetchone()
    assert "notification_status" in scan_columns
    assert job == ("Legacy Co", "Legacy Job")
    assert old_run == ("success", "legacy record")

    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert backups
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT company FROM jobs WHERE id = 7").fetchone() == ("Legacy Co",)


def test_repository_failed_migration_keeps_original_schema_data_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "old.sqlite"
    _make_old_schema_database(db_path)
    original_ensure_columns = JobRepository._ensure_columns

    def fail_mid_migration(self, conn, table, columns):
        if table == "scan_runs":
            raise RuntimeError("injected migration failure")
        return original_ensure_columns(self, conn, table, columns)

    monkeypatch.setattr(JobRepository, "_ensure_columns", fail_mid_migration)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        JobRepository(db_path).init_schema()

    conn = sqlite3.connect(db_path)
    try:
        jobs_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        scan_columns = {row[1] for row in conn.execute("PRAGMA table_info(scan_runs)")}
        job = conn.execute("SELECT company, title FROM jobs WHERE id = 7").fetchone()
    finally:
        conn.close()
    assert "raw_title" not in jobs_columns
    assert "notification_status" not in scan_columns
    assert job == ("Legacy Co", "Legacy Job")

    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert backups
    backup = sqlite3.connect(backups[0])
    try:
        assert backup.execute("SELECT COUNT(*) FROM scan_runs").fetchone() == (1,)
    finally:
        backup.close()

    monkeypatch.setattr(JobRepository, "_ensure_columns", original_ensure_columns)
    JobRepository(db_path).init_schema()
