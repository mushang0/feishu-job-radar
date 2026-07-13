from pathlib import Path

import pytest
import yaml

from jobpicky.config import load_config, save_config


ROOT = Path(__file__).resolve().parents[1]


def test_public_surface_does_not_ship_editable_credential_template():
    assert not (ROOT / "config.example.yaml").exists()


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

    assert "uvx --python 3.12 jobpicky" in text
    assert "自动创建" in text
    assert "git clone" not in text
    assert "python -m venv" not in text
    assert "pip install" not in text
    assert "YOUR_TABLE_ID" not in text
    assert "岗位ID（单行文本）" not in text
    assert "migrate-feishu" not in text

    developer = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
    assert "python -m venv" in developer
    assert "python scripts/release_check.py" in developer


def test_project_exposes_launcher_and_builds_without_desktop_path():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert 'jobpicky = "jobpicky.launcher:main"' in pyproject
    assert "python scripts/release_check.py" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "3.12" in workflow
    assert "PySide6" not in pyproject
    assert "PyInstaller" not in workflow


def test_legacy_desktop_and_script_paths_are_removed():
    assert not (ROOT / "start.bat").exists()
    assert not (ROOT / "start.ps1").exists()
    assert not (ROOT / "run_daily.bat").exists()
    assert not (ROOT / "packaging").exists()


def test_init_help_describes_workspace_creation(capsys):
    from jobpicky.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main(["init", "--help"])

    assert exit_info.value.code == 0
    assert "工作台" in capsys.readouterr().out
