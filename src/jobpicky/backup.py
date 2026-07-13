from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SQLiteBackup:
    backup_path: Path
    metadata_path: Path


class BackupService:
    """Create self-describing, restorable snapshots without touching the source."""

    def __init__(self, backup_directory: str | Path):
        self.backup_directory = Path(backup_directory)

    def backup_sqlite(self, database_path: str | Path, *, source: str) -> SQLiteBackup:
        database_path = Path(database_path)
        if not database_path.is_file():
            raise FileNotFoundError(database_path)

        self.backup_directory.mkdir(parents=True, exist_ok=True)
        created_at = _utc_now()
        filename = f"{_safe_name(source)}-{database_path.stem}-{created_at.replace(':', '').replace('-', '')}.sqlite"
        backup_path = self.backup_directory / filename
        temporary_path = backup_path.with_suffix(".sqlite.tmp")
        try:
            source_connection = sqlite3.connect(database_path)
            target_connection = sqlite3.connect(temporary_path)
            try:
                source_connection.backup(target_connection)
            finally:
                target_connection.close()
                source_connection.close()
            os.replace(temporary_path, backup_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        metadata = {
            "format_version": 1,
            "created_at": created_at,
            "source": source,
            "backup_file": backup_path.name,
            "sha256": _sha256(backup_path),
        }
        metadata_path = backup_path.with_suffix(".json")
        _write_json(metadata_path, metadata)
        return SQLiteBackup(backup_path=backup_path, metadata_path=metadata_path)


def write_feishu_backup(
    pages: Iterable[Iterable[dict[str, Any]]], backup_directory: str | Path, *, source: str = "feishu"
) -> Path:
    """Persist already-fetched Feishu pages while removing credential-shaped fields."""
    directory = Path(backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()
    output = directory / f"{_safe_name(source)}-records-{created_at.replace(':', '').replace('-', '')}.json"
    records = [_redact_credentials(record) for page in pages for record in page]
    _write_json(output, {"format_version": 1, "created_at": created_at, "source": source, "records": records})
    return output


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "backup"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _redact_credentials(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_credentials(item)
            for key, item in value.items()
            if not any(marker in key.lower() for marker in ("secret", "token", "authorization", "webhook", "password"))
        }
    if isinstance(value, list):
        return [_redact_credentials(item) for item in value]
    return value
