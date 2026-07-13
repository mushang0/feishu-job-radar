from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..paths import AppPaths, LegacyProjectPaths


@dataclass(frozen=True, slots=True)
class MigrationResult:
    migrated: bool
    source_root: str = ""
    copied_config: bool = False
    copied_database: bool = False
    database_integrity: str = "not_checked"


def migrate_legacy_project(legacy: LegacyProjectPaths, target: AppPaths) -> MigrationResult:
    """Copy one legacy checkout into the user profile without deleting it."""
    if not legacy.exists():
        return MigrationResult(migrated=False)
    target.ensure_runtime_directories()
    copied_config = False
    copied_database = False

    if legacy.config.is_file() and not target.config.exists():
        _atomic_copy(legacy.config, target.config)
        copied_config = True

    integrity = "not_checked"
    if legacy.database.is_file() and not target.database.exists():
        integrity = _sqlite_integrity(legacy.database)
        if integrity != "ok":
            raise ValueError(f"旧版 SQLite 完整性校验失败：{integrity}")
        _atomic_copy(legacy.database, target.database)
        copied_database = True

    payload = {
        "format_version": 1,
        "migrated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_root": str(legacy.root),
        "copied_config": copied_config,
        "copied_database": copied_database,
        "database_integrity": integrity,
    }
    target.migration_state.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return MigrationResult(
        migrated=True,
        source_root=str(legacy.root),
        copied_config=copied_config,
        copied_database=copied_database,
        database_integrity=integrity,
    )


def _sqlite_integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def _atomic_copy(source: Path, target: Path) -> None:
    handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
