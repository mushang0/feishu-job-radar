from pathlib import Path

from jobpicky.models import Job
from jobpicky.storage import JobRepository


def test_audit_classifies_records_by_local_record_id_and_reports_discrepancies(tmp_path: Path):
    from jobpicky.audit import audit_feishu_records

    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    first = repository.upsert_job(Job(dedupe_key="source:1", company="One", title="Engineer"))
    second = repository.upsert_job(Job(dedupe_key="source:2", company="Two", title="Designer"))
    repository.mark_sync(first.job_id, "synced", record_id="rec-1")
    repository.mark_sync(second.job_id, "synced", record_id="rec-missing")
    report = audit_feishu_records(
        repository,
        [
            {"record_id": "rec-1", "fields": {"求职状态": "待处理"}},
            {"record_id": "rec-remote", "fields": {"求职状态": "未知状态"}},
            {"fields": {"求职状态": "待处理"}},
        ],
    )

    assert report.only_local_job_ids == [second.job_id]
    assert report.only_remote_record_ids == ["rec-remote"]
    assert report.duplicate_job_ids == []
    assert report.blank_record_ids == ["record-3"]
    assert report.unknown_statuses == {"rec-remote": "未知状态"}


def test_recovery_normalizes_known_statuses_and_preserves_unknown_statuses(tmp_path: Path):
    from jobpicky.audit import recover_user_states

    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    known = repository.upsert_job(Job(dedupe_key="source:known", company="Known", title="Engineer"))
    unknown = repository.upsert_job(Job(dedupe_key="source:unknown", company="Unknown", title="Engineer"))
    repository.mark_sync(known.job_id, "synced", record_id="rec-known")
    repository.mark_sync(unknown.job_id, "synced", record_id="rec-unknown")
    repository.update_user_state(unknown.job_id, "收藏", "existing note")

    result = recover_user_states(
        repository,
        [
            {
                "record_id": "rec-known",
                "fields": {
                    "求职状态": "收藏",
                    "备注": [{"text": "from Feishu"}],
                },
            },
            {"record_id": "rec-unknown", "fields": {"求职状态": "自定义状态", "备注": "overwrite me"}},
        ],
    )

    saved_known = repository.get_job_with_match(known.job_id)
    saved_unknown = repository.get_job_with_match(unknown.job_id)
    assert result.updated_count == 1
    assert result.unknown_statuses == {"rec-unknown": "自定义状态"}
    assert saved_known["user_status"] == "收藏"
    assert saved_known["note"] == "from Feishu"
    assert saved_known["next_action"] == ""
    assert saved_known["apply_url_manual"] == ""
    assert saved_unknown["user_status"] == "收藏"
    assert saved_unknown["note"] == "existing note"


def test_legacy_personal_table_statuses_are_not_silently_migrated():
    from jobpicky.audit import normalize_status

    assert normalize_status("未看") is None
    assert normalize_status("已收藏") is None


def test_recovery_quarantines_unknown_record_ids(tmp_path: Path):
    from jobpicky.audit import recover_user_states

    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    job = repository.upsert_job(Job(dedupe_key="source:duplicate", company="Safe", title="Engineer"))
    repository.update_user_state(job.job_id, "收藏", "keep me", next_action="2026-08-01")

    result = recover_user_states(
        repository,
        [
            {"record_id": "rec-a", "fields": {"求职状态": "不合适"}},
            {"record_id": "rec-b", "fields": {"求职状态": "已结束"}},
        ],
    )

    saved = repository.get_job_with_match(job.job_id)
    assert result.updated_count == 0
    assert result.skipped_record_ids == ["rec-a", "rec-b"]
    assert saved["user_status"] == "收藏"
    assert saved["note"] == "keep me"
    assert saved["next_action"] == "2026-08-01"


def test_check_command_only_reads_feishu_records(tmp_path: Path, monkeypatch, capsys):
    from jobpicky.cli import main

    database = tmp_path / "jobs.sqlite"
    repository = JobRepository(database)
    repository.init_schema()
    job = repository.upsert_job(Job(dedupe_key="source:check", company="Check", title="Engineer"))
    repository.mark_sync(job.job_id, "synced", record_id="rec-check")
    config = tmp_path / "config.yaml"
    config.write_text("feishu: {}\n", encoding="utf-8")

    class Client:
        def __init__(self, _config):
            pass

        def list_all_records(self):
            return [{"record_id": "rec-check", "fields": {"求职状态": "待处理"}}]

    monkeypatch.setattr("jobpicky.cli.FeishuBitableClient", Client)
    assert main(["--config", str(config), "--db", str(database), "check"]) == 0
    assert "remote_record_count=1" in capsys.readouterr().out
