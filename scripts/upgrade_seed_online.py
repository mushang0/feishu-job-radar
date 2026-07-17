"""Build a sanitized v2 seed by fetching every stored WonderCV detail page once."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobpicky.storage import JobRepository  # noqa: E402
from jobpicky.wondercv import EXTRACTION_VERSION, merge_detail_into_job, parse_wondercv_detail  # noqa: E402


DEFAULT_SOURCE = ROOT / "src" / "jobpicky" / "resources" / "jobs_seed.sqlite"
DEFAULT_OUTPUT = ROOT / ".test-results" / "seed-upgrade" / "jobs_seed_v2.sqlite"
DEFAULT_CACHE = ROOT / ".test-results" / "seed-upgrade" / "html-cache"
PRIVATE_TABLES = ("job_matches", "recommended_jobs", "job_user_state", "feishu_sync", "scan_runs")


def _cached_html(url: str, cache_dir: Path, timeout: float = 25) -> str:
    cache_path = cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            html = response.text
            if not html.strip():
                raise RuntimeError("empty detail response")
            cache_dir.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(prefix=f".{cache_path.name}.", dir=cache_dir)
            os.close(handle)
            temporary = Path(temporary_name)
            try:
                temporary.write_text(html, encoding="utf-8")
                os.replace(temporary, cache_path)
            finally:
                temporary.unlink(missing_ok=True)
            return html
        except Exception as exc:  # pragma: no cover - exercised against the live source
            error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"detail fetch failed after retries: {error}")


def upgrade_seed(
    source: Path,
    output: Path,
    cache_dir: Path,
    *,
    cutoff: str,
    workers: int = 4,
    overwrite: bool = False,
) -> dict[str, int]:
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("source and output must differ")
    if output.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        shutil.copy2(source, temporary)
        repository = JobRepository(temporary)
        repository.init_schema()
        rows = repository.list_stored_jobs()
        with repository.connect() as connection:
            connection.execute("DELETE FROM job_positions")

        failures: list[str] = []
        completed = 0

        def fetch(row: dict) -> tuple[dict, object]:
            url = str(row.get("detail_url") or "")
            if not url:
                raise RuntimeError(f"job {row.get('id')} has no detail_url")
            detail = parse_wondercv_detail(_cached_html(url, cache_dir))
            if not detail.raw_text:
                raise RuntimeError(f"job {row.get('id')} produced empty detail text")
            return row, detail

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch, row): row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    stored, detail = future.result()
                    job = repository.job_from_row(stored)
                    repository.upsert_job(merge_detail_into_job(job, detail))
                    completed += 1
                    if completed % 25 == 0 or completed == len(rows):
                        print(f"upgraded {completed}/{len(rows)}", flush=True)
                except Exception as exc:
                    failures.append(f"{row.get('id')} {row.get('detail_url')}: {exc}")
        if failures:
            raise RuntimeError("online seed upgrade failed:\n" + "\n".join(failures[:20]))

        with repository.connect() as connection:
            for table in PRIVATE_TABLES:
                connection.execute(f"DELETE FROM {table}")
            connection.execute(
                "DELETE FROM job_positions WHERE job_id IN (SELECT id FROM jobs WHERE collected_date >= ?)",
                (cutoff,),
            )
            connection.execute("DELETE FROM jobs WHERE collected_date >= ?", (cutoff,))
            connection.execute("UPDATE jobs SET last_checked = NULL")
            connection.execute("UPDATE job_positions SET created_at = NULL, updated_at = NULL")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            position_count = connection.execute("SELECT COUNT(*) FROM job_positions").fetchone()[0]
            current_count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE extraction_version = ? AND parse_status = 'detail_ready'",
                (EXTRACTION_VERSION,),
            ).fetchone()[0]
        if integrity != "ok" or foreign_keys or current_count != job_count:
            raise RuntimeError(
                f"generated seed validation failed: integrity={integrity}, foreign_keys={len(foreign_keys)}, "
                f"current={current_count}/{job_count}"
            )
        os.replace(temporary, output)
        return {"fetched": completed, "jobs": job_count, "positions": position_count}
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--cutoff", default="2026-07-14")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = upgrade_seed(
        args.source, args.output, args.cache_dir, cutoff=args.cutoff, workers=args.workers, overwrite=args.overwrite
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
