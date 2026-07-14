"""Build the distributable SQLite seed from its canonical JSON source."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobpicky.storage import JobRepository  # noqa: E402


DEFAULT_SOURCE = ROOT / "src" / "jobpicky" / "resources" / "jobs_seed_source.json"
DEFAULT_OUTPUT = ROOT / "src" / "jobpicky" / "resources" / "jobs_seed.sqlite"


def build_seed(source: Path, output: Path) -> int:
    document = json.loads(source.read_text(encoding="utf-8"))
    if document.get("format_version") != 1 or document.get("table") != "jobs":
        raise ValueError("unsupported seed source format")
    columns = document.get("columns")
    jobs = document.get("jobs")
    if not isinstance(columns, list) or not columns or not isinstance(jobs, list):
        raise ValueError("seed source must contain columns and jobs lists")
    if len(columns) != len(set(columns)):
        raise ValueError("seed source contains duplicate columns")
    expected_keys = set(columns)
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or set(job) != expected_keys:
            raise ValueError(f"job at index {index} does not match declared columns")

    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        repository = JobRepository(temporary)
        repository.init_schema()
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        with repository.connect() as connection:
            connection.executemany(
                f"INSERT INTO jobs ({quoted_columns}) VALUES ({placeholders})",
                ([job[column] for column in columns] for job in jobs),
            )
        with repository.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if integrity != "ok" or count != len(jobs):
            raise sqlite3.DatabaseError("generated seed failed validation")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(jobs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = build_seed(args.source, args.output)
    print(f"built {args.output} with {count} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
