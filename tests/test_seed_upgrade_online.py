import sqlite3
from pathlib import Path

from jobpicky.models import Job
from jobpicky.storage import JobRepository
from scripts import upgrade_seed_online


def test_upgrade_seed_fetches_all_jobs_sanitizes_and_applies_cutoff(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    repository = JobRepository(source)
    repository.init_schema()
    kept = repository.upsert_job(
        Job(
            dedupe_key="keep",
            company="甲公司",
            title="校园招聘",
            detail_url="https://example.test/keep",
            collected_date="2026-07-13",
        )
    )
    removed = repository.upsert_job(
        Job(
            dedupe_key="remove",
            company="乙公司",
            title="校园招聘",
            detail_url="https://example.test/remove",
            collected_date="2026-07-14",
        )
    )
    with repository.connect() as connection:
        connection.execute("INSERT INTO job_matches (job_id, is_relevant) VALUES (?, 1)", (kept.job_id,))
        connection.execute(
            "INSERT INTO recommended_jobs (recommendation_date, job_id, recommend_reason, created_at) "
            "VALUES ('2026-07-13', ?, 'test', '2026-07-13T00:00:00')",
            (removed.job_id,),
        )

    monkeypatch.setattr(
        upgrade_seed_online,
        "_cached_html",
        lambda *_: "<main><h2>招聘岗位</h2><p>嵌入式工程师（深圳）：负责驱动开发。</p></main>",
    )

    result = upgrade_seed_online.upgrade_seed(
        source, output, tmp_path / "cache", cutoff="2026-07-14", workers=1
    )

    assert result == {"fetched": 2, "jobs": 1, "positions": 1}
    connection = sqlite3.connect(output)
    try:
        assert connection.execute("SELECT dedupe_key FROM jobs").fetchall() == [("keep",)]
        assert connection.execute("SELECT title FROM job_positions").fetchall() == [("嵌入式工程师",)]
        for table in upgrade_seed_online.PRIVATE_TABLES:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        connection.close()
