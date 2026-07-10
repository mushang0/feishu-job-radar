from pathlib import Path

from job_monitor.models import Job
from job_monitor.storage import JobRepository


def test_audit_classifies_records_by_job_id_and_reports_discrepancies(tmp_path: Path):
    from job_monitor.audit import audit_feishu_records

    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    first = repository.upsert_job(Job(dedupe_key="source:1", company="One", title="Engineer"))
    second = repository.upsert_job(Job(dedupe_key="source:2", company="Two", title="Designer"))
    report = audit_feishu_records(
        repository,
        [
            {"record_id": "rec-1", "fields": {"岗位ID": str(first.job_id), "求职状态": "待处理"}},
            {"record_id": "rec-duplicate", "fields": {"岗位ID": str(first.job_id), "求职状态": "收藏"}},
            {"record_id": "rec-remote", "fields": {"岗位ID": "999", "求职状态": "未知状态"}},
            {"record_id": "rec-blank", "fields": {"求职状态": "待处理"}},
        ],
    )

    assert report.only_local_job_ids == [second.job_id]
    assert report.only_remote_record_ids == ["rec-remote"]
    assert report.duplicate_job_ids == [first.job_id]
    assert report.blank_record_ids == ["rec-blank"]
    assert report.unknown_statuses == {"rec-remote": "未知状态"}


def test_recovery_normalizes_known_statuses_and_preserves_unknown_statuses(tmp_path: Path):
    from job_monitor.audit import recover_user_states

    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.init_schema()
    known = repository.upsert_job(Job(dedupe_key="source:known", company="Known", title="Engineer"))
    unknown = repository.upsert_job(Job(dedupe_key="source:unknown", company="Unknown", title="Engineer"))
    repository.update_user_state(unknown.job_id, "收藏", "existing note")

    result = recover_user_states(
        repository,
        [
            {
                "record_id": "rec-known",
                "fields": {
                    "岗位ID": str(known.job_id),
                    "求职状态": "收藏",
                    "备注": [{"text": "from Feishu"}],
                    "下一步行动": [{"text": "2026-07-15"}],
                },
            },
            {"record_id": "rec-unknown", "fields": {"岗位ID": str(unknown.job_id), "求职状态": "自定义状态", "备注": "overwrite me"}},
        ],
    )

    saved_known = repository.get_job_with_match(known.job_id)
    saved_unknown = repository.get_job_with_match(unknown.job_id)
    assert result.updated_count == 1
    assert result.unknown_statuses == {"rec-unknown": "自定义状态"}
    assert saved_known["user_status"] == "收藏"
    assert saved_known["note"] == "from Feishu"
    assert saved_known["next_action"] == "2026-07-15"
    assert saved_known["apply_url_manual"] == ""
    assert saved_unknown["user_status"] == "收藏"
    assert saved_unknown["note"] == "existing note"


def test_legacy_personal_table_statuses_are_not_silently_migrated():
    from job_monitor.audit import normalize_status

    assert normalize_status("未看") is None
    assert normalize_status("已收藏") is None


def test_check_command_only_reads_feishu_records(tmp_path: Path, monkeypatch, capsys):
    from job_monitor.cli import main

    database = tmp_path / "jobs.sqlite"
    repository = JobRepository(database)
    repository.init_schema()
    job = repository.upsert_job(Job(dedupe_key="source:check", company="Check", title="Engineer"))
    config = tmp_path / "config.yaml"
    config.write_text("feishu: {}\n", encoding="utf-8")

    class Client:
        def __init__(self, _config):
            pass

        def list_all_records(self):
            return [{"record_id": "rec-check", "fields": {"岗位ID": str(job.job_id), "求职状态": "待处理"}}]

    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)
    assert main(["--config", str(config), "--db", str(database), "check"]) == 0
    assert "remote_record_count=1" in capsys.readouterr().out
