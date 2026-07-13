from __future__ import annotations

import sys
import zipfile
from glob import glob
from pathlib import Path


REQUIRED_SUFFIXES = {
    "job_monitor/resources/jobs_seed.sqlite",
    "job_monitor/web/templates/index.html",
    "job_monitor/launcher.py",
    "job_monitor/web/app.py",
}

FORBIDDEN_PARTS = {
    "desktop.py",
    "desktop_entry.py",
    "feishu-job-radar.spec",
    "start.bat",
    "start.ps1",
    "run_daily.bat",
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        raise SystemExit("usage: verify_wheel.py <wheel>")

    matches = glob(args[0])
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one wheel, found {len(matches)}: {args[0]}")
    wheel = Path(matches[0]).resolve()
    if not wheel.is_file():
        raise SystemExit(f"wheel does not exist: {wheel}")

    with zipfile.ZipFile(wheel) as archive:
        entries = set(archive.namelist())
        seed = archive.getinfo("job_monitor/resources/jobs_seed.sqlite")

    missing = sorted(REQUIRED_SUFFIXES - entries)
    forbidden = sorted(
        entry
        for entry in entries
        if any(part in entry.split("/") for part in FORBIDDEN_PARTS)
        or entry.startswith(("build/", "dist/", "packaging/"))
    )
    if missing:
        raise SystemExit(f"wheel is missing required resources: {missing}")
    if forbidden:
        raise SystemExit(f"wheel contains forbidden files: {forbidden}")
    if seed.file_size < 1_000_000:
        raise SystemExit(f"packaged seed database is unexpectedly small: {seed.file_size}")

    print(
        f"wheel verified: {wheel.name}; entries={len(entries)}; "
        f"seed_bytes={seed.file_size}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
