import hashlib
import json
import sqlite3
from pathlib import Path

from job_monitor.backup import BackupService, write_feishu_backup
from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_schema_upgrade_backs_up_existing_database_before_adding_user_fields(tmp_path: Path):
    database = tmp_path / "jobs.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE job_user_state (job_id INTEGER UNIQUE, status TEXT, note TEXT)")

    repository = JobRepository(database)
    repository.init_schema()

    columns = {row[1] for row in repository.connect().execute("PRAGMA table_info(job_user_state)")}
    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert {"next_action", "apply_url_manual"} <= columns
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        backed_up_columns = {row[1] for row in conn.execute("PRAGMA table_info(job_user_state)")}
    assert "next_action" not in backed_up_columns


def test_sqlite_backup_writes_timestamp_source_and_checksum_metadata(tmp_path: Path):
    database = tmp_path / "jobs.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sample (value TEXT)")
        conn.execute("INSERT INTO sample VALUES ('safe')")

    result = BackupService(tmp_path / "backups").backup_sqlite(database, source="schema-upgrade")

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source"] == "schema-upgrade"
    assert metadata["created_at"].endswith("Z")
    assert metadata["sha256"] == hashlib.sha256(result.backup_path.read_bytes()).hexdigest()
    with sqlite3.connect(result.backup_path) as conn:
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "safe"


def test_feishu_backup_serializes_paginated_records_without_credentials(tmp_path: Path):
    output = write_feishu_backup(
        [[{"record_id": "rec_1", "fields": {"status": "pending"}, "app_secret": "do-not-store"}]],
        tmp_path / "backups",
        source="feishu-audit",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source"] == "feishu-audit"
    assert payload["records"] == [{"record_id": "rec_1", "fields": {"status": "pending"}}]
    assert "do-not-store" not in output.read_text(encoding="utf-8")


def test_user_state_persists_next_action_and_manual_application_url(tmp_path: Path):
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    job_id = repository.upsert_job(Job(dedupe_key="source:1", company="Example", title="Engineer")).job_id

    repository.update_user_state(
        job_id,
        "待处理",
        "follow up",
        apply_url_manual="https://careers.example/apply",
        next_action="2026-07-15",
    )

    saved = repository.get_job_with_match(job_id)
    assert saved["apply_url_manual"] == "https://careers.example/apply"
    assert saved["next_action"] == "2026-07-15"
