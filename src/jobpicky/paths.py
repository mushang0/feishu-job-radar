from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_HOME_ENV = "JOBPICKY_HOME"
APP_DIRECTORY_NAME = "JobPicky"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Filesystem locations owned by one local JobPicky profile.

    The explicit ``root`` makes services deterministic in tests and keeps them
    independent from the process working directory.  The launcher will use
    :meth:`default`; tests and migration tooling can inject a temporary root.
    """

    root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        configured = os.environ.get(APP_HOME_ENV)
        if configured:
            return cls(Path(configured).expanduser())
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return cls(Path(local_app_data) / APP_DIRECTORY_NAME)
        # Keep non-Windows development environments usable without adding a
        # platform-specific dependency.  Windows remains the primary target.
        return cls(Path.home() / ".local" / "share" / APP_DIRECTORY_NAME)

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def database(self) -> Path:
        return self.root / "jobs.sqlite"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def migration_state(self) -> Path:
        return self.root / "migration-state.json"

    def ensure_runtime_directories(self) -> None:
        for directory in (self.root, self.logs, self.exports, self.backups):
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def legacy_project(cls, project_root: str | Path) -> "LegacyProjectPaths":
        return LegacyProjectPaths(Path(project_root).resolve())


@dataclass(frozen=True, slots=True)
class LegacyProjectPaths:
    """Read-only view of the pre-WebUI project layout used by migration."""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def database(self) -> Path:
        return self.root / "data" / "jobs.sqlite"

    @property
    def seed(self) -> Path:
        return self.root / "data" / "jobs_seed.sqlite"

    def exists(self) -> bool:
        return self.config.is_file() or self.database.is_file()
