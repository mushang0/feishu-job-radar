import sqlite3
from pathlib import Path

from jobpicky.seed import restore_seed_database


def _make_seed(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table marker (value text)")
    connection.execute("insert into marker values (?)", (value,))
    connection.commit()
    connection.close()


def _marker(path: Path) -> str:
    connection = sqlite3.connect(path)
    value = connection.execute("select value from marker").fetchone()[0]
    connection.close()
    return value


def test_restore_seed_creates_missing_runtime_database(tmp_path: Path, monkeypatch):
    seed = tmp_path / "jobs_seed.sqlite"
    target = tmp_path / "data" / "jobs.sqlite"
    _make_seed(seed, "seed")
    monkeypatch.setattr("jobpicky.seed.find_seed_database", lambda: seed)

    assert restore_seed_database(target) is True
    assert _marker(target) == "seed"


def test_restore_seed_keeps_existing_runtime_database_unless_overwrite_requested(tmp_path: Path, monkeypatch):
    seed = tmp_path / "jobs_seed.sqlite"
    target = tmp_path / "jobs.sqlite"
    _make_seed(seed, "seed")
    _make_seed(target, "existing")
    monkeypatch.setattr("jobpicky.seed.find_seed_database", lambda: seed)

    assert restore_seed_database(target) is False
    assert _marker(target) == "existing"
    assert restore_seed_database(target, overwrite=True) is True
    assert _marker(target) == "seed"
