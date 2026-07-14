from pathlib import Path

from ..seed import restore_seed_database
from ..storage import JobRepository


class DatabaseBootstrapService:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def initialize(self, *, overwrite: bool = False) -> JobRepository:
        restore_seed_database(self.database_path, overwrite=overwrite)
        repository = JobRepository(self.database_path)
        repository.init_schema()
        return repository
