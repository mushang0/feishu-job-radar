from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import validate_config


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ok: bool
    errors: tuple[str, ...]
    database_writable: bool


def preflight_check(config: dict, database_path: str | Path) -> PreflightResult:
    errors = validate_config(config)
    path = Path(database_path)
    writable = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path):
            pass
        writable = True
    except sqlite3.Error:
        errors.append("本地数据目录不可读写")
    return PreflightResult(not errors, tuple(errors), writable)
