from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class SeedDatabaseError(RuntimeError):
    pass


def find_seed_database() -> Path:
    """Locate the bundled job baseline from a checkout or installed project."""
    frozen_root = Path(getattr(__import__("sys"), "_MEIPASS", ""))
    candidates = (
        Path.cwd() / "data" / "jobs_seed.sqlite",
        frozen_root / "data" / "jobs_seed.sqlite",
        Path(__file__).resolve().parents[2] / "data" / "jobs_seed.sqlite",
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    raise SeedDatabaseError("找不到 data/jobs_seed.sqlite；请重新获取完整项目文件后重试")


def restore_seed_database(target: str | Path, *, overwrite: bool = False) -> bool:
    """Atomically create or replace a runtime database from the shipped seed.

    Returns True when a copy was made and False when an existing target was kept.
    """
    destination = Path(target)
    if destination.exists() and not overwrite:
        return False

    source = find_seed_database()
    if source.resolve() == destination.resolve():
        raise SeedDatabaseError("seed 数据库不能作为运行数据库直接使用")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size:
            raise SeedDatabaseError("seed 数据库复制不完整")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return True
