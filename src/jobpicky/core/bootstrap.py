from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
import sqlite3

from ..seed import find_seed_database, restore_seed_database
from ..storage import JobRepository


@dataclass(frozen=True, slots=True)
class LocalDatabaseInspection:
    status: str
    job_count: int = 0

    @property
    def valid(self) -> bool:
        return self.status == "valid"


_REQUIRED_LOCAL_TABLES = {
    "jobs",
    "job_matches",
    "recommended_jobs",
    "job_user_state",
    "scan_runs",
    "feishu_sync",
}


def inspect_local_database(database_path: str | Path) -> LocalDatabaseInspection:
    """Inspect a local database without creating files or changing its schema."""
    path = Path(database_path)
    if not path.is_file():
        return LocalDatabaseInspection("missing")
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not _REQUIRED_LOCAL_TABLES.issubset(tables):
                return LocalDatabaseInspection("invalid")
            job_count = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    except (OSError, sqlite3.Error):
        return LocalDatabaseInspection("invalid")
    if job_count == 0:
        return LocalDatabaseInspection("empty_schema")
    return LocalDatabaseInspection("valid", job_count)


def packaged_seed_job_count() -> int:
    inspection = inspect_local_database(find_seed_database())
    if not inspection.valid:
        raise RuntimeError("packaged seed database is not valid")
    return inspection.job_count


class DatabaseBootstrapService:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def initialize(self, *, overwrite: bool = False) -> JobRepository:
        inspection = inspect_local_database(self.database_path)
        restore_seed_database(
            self.database_path,
            overwrite=overwrite or not inspection.valid,
        )
        repository = JobRepository(self.database_path)
        repository.init_schema()
        return repository
