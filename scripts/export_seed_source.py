"""Export the legacy SQLite seed into the reviewable canonical JSON source."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "src" / "jobpicky" / "resources" / "jobs_seed.sqlite"
DEFAULT_OUTPUT = ROOT / "src" / "jobpicky" / "resources" / "jobs_seed_source.json"


def export_seed_source(database: Path, output: Path) -> int:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"seed integrity check failed: {integrity}")
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(jobs)")]
        if not columns:
            raise sqlite3.DatabaseError("seed does not contain a jobs table")
        jobs = [dict(row) for row in connection.execute("SELECT * FROM jobs ORDER BY id")]
    finally:
        connection.close()

    document = {
        "format_version": 1,
        "table": "jobs",
        "columns": columns,
        "jobs": jobs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(jobs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = export_seed_source(args.database, args.output)
    print(f"exported {count} jobs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
