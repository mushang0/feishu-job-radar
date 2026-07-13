from pathlib import Path

from job_monitor.paths import AppPaths
from job_monitor.seed import find_seed_database


def test_default_paths_use_explicit_home_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FEISHU_JOB_RADAR_HOME", str(tmp_path / "profile"))

    paths = AppPaths.default()

    assert paths.root == tmp_path / "profile"
    assert paths.config == paths.root / "config.yaml"
    assert paths.database == paths.root / "jobs.sqlite"
    assert paths.logs == paths.root / "logs"
    assert paths.exports == paths.root / "exports"
    assert paths.backups == paths.root / "backups"


def test_runtime_directories_are_created_under_profile_root(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")

    paths.ensure_runtime_directories()

    assert all(directory.is_dir() for directory in (paths.root, paths.logs, paths.exports, paths.backups))


def test_seed_is_available_as_a_packaged_resource():
    seed = find_seed_database()

    assert seed.as_posix().endswith("job_monitor/resources/jobs_seed.sqlite")
    assert seed.stat().st_size > 1_000_000
