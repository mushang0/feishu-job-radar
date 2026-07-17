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
    if document.get("format_version") == 1 and document.get("table") == "jobs":
        tables = {"jobs": {"columns": document.get("columns"), "rows": document.get("jobs")}}
    elif document.get("format_version") == 2 and isinstance(document.get("tables"), dict):
        tables = document["tables"]
    else:
        raise ValueError("unsupported seed source format")
    for table, snapshot in tables.items():
        columns = snapshot.get("columns") if isinstance(snapshot, dict) else None
        rows = snapshot.get("rows") if isinstance(snapshot, dict) else None
        if not isinstance(columns, list) or not columns or not isinstance(rows, list):
            raise ValueError(f"seed table {table} must contain columns and rows lists")
        if len(columns) != len(set(columns)):
            raise ValueError(f"seed table {table} contains duplicate columns")
        expected_keys = set(columns)
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != expected_keys:
                raise ValueError(f"{table} row at index {index} does not match declared columns")

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
        with repository.connect() as connection:
            for table in ("jobs", "job_positions"):
                if table not in tables:
                    continue
                columns = tables[table]["columns"]
                rows = tables[table]["rows"]
                placeholders = ", ".join("?" for _ in columns)
                quoted_columns = ", ".join(f'"{column}"' for column in columns)
                connection.executemany(
                    f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders})",
                    ([row[column] for column in columns] for row in rows),
                )
        with repository.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            positions = connection.execute("SELECT COUNT(*) FROM job_positions").fetchone()[0]
        expected_jobs = len(tables["jobs"]["rows"])
        expected_positions = len(tables.get("job_positions", {}).get("rows", []))
        if integrity != "ok" or count != expected_jobs or positions != expected_positions:
            raise sqlite3.DatabaseError("generated seed failed validation")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return expected_jobs


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
