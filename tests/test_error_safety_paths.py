from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_monitor import cli
from job_monitor.error_safety import safe_exception_detail
from job_monitor.logging_utils import SensitiveDataFilter
from job_monitor.seed import SeedDatabaseError
from job_monitor.web import app as web_app
from job_monitor.paths import AppPaths


RAW_SECRET_ERROR = (
    "Authorization: Bearer CLI-SECRET; "
    "app_secret=VERY-SECRET; "
    "https://example.com/hook/SECRET-TOKEN"
)


def _config() -> dict:
    return {
        "user_profile": {"graduate_years": ["2027"], "role_groups": ["hardware"]},
        "feishu": {
            "base_url": "https://example.feishu.cn/base/base-token",
            "app_id": "app-id",
            "app_secret": "VERY-SECRET",
            "webhook_url": "https://example.com/hook/SECRET-TOKEN",
            "workspace_table_id": "tbl-test",
        },
    }


def _assert_no_secret(text: str) -> None:
    for secret in ("CLI-SECRET", "VERY-SECRET", "SECRET-TOKEN"):
        assert secret not in text


def _write_cli_config(path: Path) -> None:
    path.write_text(
        """
user_profile:
  graduate_years: [2027]
  role_groups: [hardware]
feishu:
  base_url: https://example.feishu.cn/base/base-token
  workspace_table_id: tbl-test
  app_id: app-id
  app_secret: VERY-SECRET
  webhook_url: https://example.com/hook/SECRET-TOKEN
""",
        encoding="utf-8",
    )


def _cli_log_text(log_dir: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in log_dir.glob("*.log"))


@pytest.fixture
def _restore_root_logging():
    yield
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()


def _assert_real_cli_failure_is_safe(
    captured, log_text: str, *, code: int, error_code: str
) -> None:
    output = captured.out + captured.err
    assert code == 1
    assert f"code={error_code}" in output
    assert "message=" in output
    combined = output + log_text
    assert RAW_SECRET_ERROR not in combined
    _assert_no_secret(combined)
    assert "Traceback" not in combined


def test_real_cli_pull_error_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_root_logging,
):
    config_path = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    _write_cli_config(config_path)
    monkeypatch.setenv("JOB_MONITOR_LOG_DIR", str(log_dir))
    monkeypatch.setattr(cli, "FeishuBitableClient", lambda config: object())
    monkeypatch.setattr(
        cli,
        "pull_user_states_from_feishu",
        lambda repo, client: (_ for _ in ()).throw(RuntimeError(RAW_SECRET_ERROR)),
    )

    code = cli.main(["--config", str(config_path), "--db", str(tmp_path / "jobs.sqlite"), "pull"])

    _assert_real_cli_failure_is_safe(
        capsys.readouterr(), _cli_log_text(log_dir), code=code, error_code="pull_failed"
    )


def test_real_cli_check_error_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_root_logging,
):
    config_path = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    _write_cli_config(config_path)
    monkeypatch.setenv("JOB_MONITOR_LOG_DIR", str(log_dir))

    class Client:
        def __init__(self, config):
            pass

        def list_all_records(self):
            raise RuntimeError(RAW_SECRET_ERROR)

    monkeypatch.setattr(cli, "FeishuBitableClient", Client)

    code = cli.main(["--config", str(config_path), "--db", str(tmp_path / "jobs.sqlite"), "check"])

    _assert_real_cli_failure_is_safe(
        capsys.readouterr(), _cli_log_text(log_dir), code=code, error_code="check_failed"
    )


def test_real_cli_init_error_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_root_logging,
):
    config_path = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    _write_cli_config(config_path)
    monkeypatch.setenv("JOB_MONITOR_LOG_DIR", str(log_dir))
    monkeypatch.setattr(
        cli,
        "collect_missing_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(RAW_SECRET_ERROR)),
    )

    code = cli.main(
        [
            "--config",
            str(config_path),
            "--db",
            str(tmp_path / "jobs.sqlite"),
            "init",
            "--output",
            str(tmp_path / "out.xlsx"),
        ]
    )

    _assert_real_cli_failure_is_safe(
        capsys.readouterr(), _cli_log_text(log_dir), code=code, error_code="initialization_failed"
    )


def test_real_cli_reset_error_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_root_logging,
):
    config_path = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    _write_cli_config(config_path)
    monkeypatch.setenv("JOB_MONITOR_LOG_DIR", str(log_dir))
    monkeypatch.setattr(
        cli,
        "find_seed_database",
        lambda: (_ for _ in ()).throw(SeedDatabaseError(RAW_SECRET_ERROR)),
    )

    code = cli.main(
        [
            "--config",
            str(config_path),
            "--db",
            str(tmp_path / "jobs.sqlite"),
            "reset",
            "--yes",
            "--output",
            str(tmp_path / "out.xlsx"),
        ]
    )

    _assert_real_cli_failure_is_safe(
        capsys.readouterr(), _cli_log_text(log_dir), code=code, error_code="reset_failed"
    )


def test_real_cli_invalid_yaml_is_caught_before_command_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_root_logging,
):
    config_path = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    config_path.write_text(
        "feishu:\n  app_secret: VERY-SECRET\n  invalid: [\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JOB_MONITOR_LOG_DIR", str(log_dir))

    code = cli.main(["--config", str(config_path), "pull"])

    _assert_real_cli_failure_is_safe(
        capsys.readouterr(), _cli_log_text(log_dir), code=code, error_code="configuration_invalid"
    )


def test_web_initialization_validation_error_is_stable_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    class FailingInitialization:
        def __init__(self, paths):
            pass

        def initialize(self, config):
            raise ValueError(RAW_SECRET_ERROR)

    monkeypatch.setattr(web_app, "InitializationService", FailingInitialization)
    client = TestClient(web_app.create_app(AppPaths(tmp_path / "profile")))

    with caplog.at_level(logging.WARNING):
        response = client.post("/api/setup/initialize")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "stage": "initialization",
        "code": "configuration_invalid",
        "message": "配置校验失败，请检查配置后重试。",
    }
    _assert_no_secret(response.text)
    _assert_no_secret(caplog.text)
    assert "Traceback" not in caplog.text


def test_web_initialization_internal_error_is_stable_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    class FailingInitialization:
        def __init__(self, paths):
            pass

        def initialize(self, config):
            raise RuntimeError(RAW_SECRET_ERROR)

    monkeypatch.setattr(web_app, "InitializationService", FailingInitialization)
    client = TestClient(web_app.create_app(AppPaths(tmp_path / "profile")))

    with caplog.at_level(logging.ERROR):
        response = client.post("/api/setup/initialize")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "stage": "initialization",
        "code": "initialization_failed",
        "message": "初始化失败，请查看日志后重试。",
    }
    _assert_no_secret(response.text)
    _assert_no_secret(caplog.text)
    assert "Traceback" not in caplog.text


def test_web_initialization_invalid_yaml_is_structured_and_redacted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    paths = AppPaths(tmp_path / "profile")
    paths.ensure_runtime_directories()
    paths.config.write_text(
        "feishu:\n  app_secret: VERY-SECRET\n  invalid: [\n",
        encoding="utf-8",
    )
    client = TestClient(web_app.create_app(paths), raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING):
        response = client.post("/api/setup/initialize")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "stage": "initialization",
        "code": "configuration_invalid",
        "message": "配置校验失败，请检查配置后重试。",
    }
    _assert_no_secret(response.text)
    _assert_no_secret(caplog.text)
    assert "Traceback" not in response.text + caplog.text


def test_cli_pull_error_is_redacted_from_stdout_stderr_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(cli, "FeishuBitableClient", lambda config: object())
    monkeypatch.setattr(
        cli,
        "pull_user_states_from_feishu",
        lambda repo, client: (_ for _ in ()).throw(RuntimeError(RAW_SECRET_ERROR)),
    )

    with caplog.at_level(logging.ERROR):
        assert cli._run_pull(_config(), str(tmp_path / "jobs.sqlite")) == 1
    captured = capfd.readouterr()
    _assert_no_secret(captured.out + captured.err + caplog.text)
    assert "Traceback" not in captured.err + caplog.text


def test_cli_check_error_is_redacted_from_stdout_stderr_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
):
    class Client:
        def __init__(self, config):
            pass

        def list_all_records(self):
            raise RuntimeError(RAW_SECRET_ERROR)

    monkeypatch.setattr(cli, "FeishuBitableClient", Client)

    with caplog.at_level(logging.ERROR):
        assert cli._run_check(_config(), str(tmp_path / "jobs.sqlite")) == 1
    captured = capfd.readouterr()
    _assert_no_secret(captured.out + captured.err + caplog.text)
    assert "Traceback" not in captured.err + caplog.text


def test_cli_init_error_is_redacted_from_stdout_stderr_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        cli,
        "collect_missing_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(RAW_SECRET_ERROR)),
    )

    with caplog.at_level(logging.ERROR):
        assert cli._run_init(
            _config(),
            str(tmp_path / "jobs.sqlite"),
            str(tmp_path / "config.yaml"),
            str(tmp_path / "out.xlsx"),
        ) == 1
    captured = capfd.readouterr()
    _assert_no_secret(captured.out + captured.err + caplog.text)
    assert "Traceback" not in captured.err + caplog.text


def test_cli_reset_error_is_redacted_from_stdout_stderr_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(
        cli,
        "find_seed_database",
        lambda: (_ for _ in ()).throw(SeedDatabaseError(RAW_SECRET_ERROR)),
    )

    with caplog.at_level(logging.ERROR):
        assert cli._run_reset(
            _config(),
            str(tmp_path / "jobs.sqlite"),
            str(tmp_path / "config.yaml"),
            str(tmp_path / "out.xlsx"),
            confirmed=True,
        ) == 1
    captured = capfd.readouterr()
    _assert_no_secret(captured.out + captured.err + caplog.text)
    assert "Traceback" not in captured.err + caplog.text


def test_logging_exception_filter_removes_traceback_and_secrets():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SensitiveDataFilter())
    logger = logging.getLogger("error-safety-traceback")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        try:
            raise RuntimeError(RAW_SECRET_ERROR)
        except RuntimeError:
            logger.exception("operation failed")
    finally:
        logger.removeHandler(handler)
        handler.close()

    output = stream.getvalue()
    _assert_no_secret(output)
    assert "operation failed" in output
    assert "Traceback" not in output


def test_safe_exception_detail_remains_safe_for_the_cli_error_helper():
    assert "CLI-SECRET" not in safe_exception_detail(RuntimeError(RAW_SECRET_ERROR), _config())
