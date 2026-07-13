import json
import sqlite3
from pathlib import Path

from jobpicky.paths import AppPaths
from jobpicky.services.migration import migrate_legacy_project


def test_migration_copies_legacy_config_and_database_without_deleting_source(tmp_path: Path):
    legacy_root = tmp_path / "legacy"
    (legacy_root / "data").mkdir(parents=True)
    (legacy_root / "config.yaml").write_text("user_profile:\n  role_groups: [硬件/嵌入式]\n", encoding="utf-8")
    with sqlite3.connect(legacy_root / "data" / "jobs.sqlite") as connection:
        connection.execute("create table marker (value text)")
        connection.execute("insert into marker values ('legacy')")

    target = AppPaths(tmp_path / "profile")
    result = migrate_legacy_project(AppPaths.legacy_project(legacy_root), target)

    assert result.migrated is True
    assert result.copied_config is True
    assert result.copied_database is True
    assert result.database_integrity == "ok"
    assert target.config.exists() and target.database.exists() and target.migration_state.exists()
    assert (legacy_root / "config.yaml").exists() and (legacy_root / "data" / "jobs.sqlite").exists()
    assert json.loads(target.migration_state.read_text(encoding="utf-8"))["source_root"] == str(legacy_root.resolve())


def test_migration_does_not_overwrite_existing_profile_files(tmp_path: Path):
    legacy_root = tmp_path / "legacy"
    (legacy_root / "data").mkdir(parents=True)
    (legacy_root / "config.yaml").write_text("legacy: true\n", encoding="utf-8")
    target = AppPaths(tmp_path / "profile")
    target.ensure_runtime_directories()
    target.config.write_text("local: true\n", encoding="utf-8")

    result = migrate_legacy_project(AppPaths.legacy_project(legacy_root), target)

    assert result.copied_config is False
    assert target.config.read_text(encoding="utf-8") == "local: true\n"
