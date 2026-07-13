from pathlib import Path

from jobpicky.diagnostics import preflight_check


def test_preflight_reports_configuration_errors_and_database_availability(tmp_path: Path):
    result = preflight_check({"user_profile": {}, "feishu": {}}, tmp_path / "jobs.sqlite")

    assert result.ok is False
    assert "至少选择一个毕业届别" in result.errors
    assert result.database_writable is True
