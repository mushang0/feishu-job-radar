from pathlib import Path

import pytest
import yaml

from job_monitor.config import load_config, save_config


ROOT = Path(__file__).resolve().parents[1]


def test_public_config_contains_only_user_inputs_and_no_real_credentials():
    config = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

    assert set(config) == {"user_profile", "feishu"}
    assert "system_taxonomy" not in config
    assert config["feishu"] == {
        "base_url": "",
        "app_id": "",
        "app_secret": "",
        "webhook_url": "",
    }
    assert "table_id" not in config["feishu"]
    assert "tenant_access_token" not in config["feishu"]


def test_saving_merged_defaults_keeps_local_config_small(tmp_path: Path):
    config = load_config(tmp_path / "missing.yaml")
    config["user_profile"]["graduate_years"] = ["2027届"]
    config["user_profile"]["role_groups"] = ["硬件/嵌入式"]
    config["feishu"].update(
        {
            "base_url": "https://example.feishu.cn/base/token",
            "app_id": "cli-app",
            "app_secret": "secret",
            "workspace_table_id": "tbl-managed",
            "workspace_schema_version": "1",
        }
    )

    path = tmp_path / "config.yaml"
    save_config(config, path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "system_taxonomy" not in saved
    assert "crawler" not in saved
    assert saved["feishu"]["workspace_table_id"] == "tbl-managed"
    assert len(path.read_text(encoding="utf-8").splitlines()) < 40


def test_saving_config_preserves_only_changed_advanced_overrides(tmp_path: Path):
    config = load_config(tmp_path / "missing.yaml")
    config["crawler"]["max_pages_daily"] = 3
    path = tmp_path / "config.yaml"

    save_config(config, path)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["crawler"] == {"max_pages_daily": 3}
    assert "system_taxonomy" not in saved


def test_readme_describes_automatic_workspace_setup_without_old_migration():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m job_monitor init" in text
    assert "自动创建" in text
    assert "YOUR_TABLE_ID" not in text
    assert "岗位ID（单行文本）" not in text
    assert "migrate-feishu" not in text


def test_project_exposes_console_script_and_windows_ci_matrix():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert 'feishu-job-radar = "job_monitor.cli:main"' in pyproject
    assert "windows-latest" in workflow
    assert "3.12" in workflow


def test_windows_daily_runner_uses_project_virtualenv_and_absolute_paths():
    runner = (ROOT / "run_daily.bat").read_text(encoding="utf-8")

    assert '.venv\\Scripts\\python.exe' in runner
    assert '"%PYTHON_EXE%" -m job_monitor' in runner
    assert '--config "%~dp0config.yaml"' in runner
    assert '--db "%~dp0data\\jobs.sqlite"' in runner


def test_init_help_describes_workspace_creation(capsys):
    from job_monitor.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main(["init", "--help"])

    assert exit_info.value.code == 0
    assert "工作台" in capsys.readouterr().out
