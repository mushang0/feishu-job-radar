"""Run the clean-install acceptance check for a release build.

Build, pip, and WebUI output is written to ``.test-results/release-check.log``
so the normal terminal output stays small enough for local and CI summaries.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

STAGES = (
    "Build package",
    "Verify wheel",
    "Create clean environment",
    "Install package",
    "Dependency check",
    "Launch outside repository",
    "WebUI health check",
    "uvx launch smoke",
    "Clean shutdown",
)


REQUIRED_WHEEL_ENTRIES = {
    "jobpicky/resources/jobs_seed.sqlite",
    "jobpicky/web/templates/index.html",
    "jobpicky/launcher.py",
    "jobpicky/web/app.py",
}

FORBIDDEN_WHEEL_PARTS = {
    "desktop.py",
    "desktop_entry.py",
    "jobpicky.spec",
    "start.bat",
    "start.ps1",
    "run_daily.bat",
}


class ReleaseCheckError(RuntimeError):
    """A concise, user-facing release-check failure."""


@dataclass(frozen=True, slots=True)
class WheelVerification:
    wheel: Path
    entry_count: int
    seed_bytes: int


def verify_wheel(wheel: Path) -> WheelVerification:
    """Verify one built wheel and return details for the release check."""
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise ValueError(f"wheel does not exist: {wheel}")

    with zipfile.ZipFile(wheel) as archive:
        entries = set(archive.namelist())
        try:
            seed = archive.getinfo("jobpicky/resources/jobs_seed.sqlite")
        except KeyError as exc:
            raise ValueError(
                "wheel is missing required resources: "
                "['jobpicky/resources/jobs_seed.sqlite']"
            ) from exc

    missing = sorted(REQUIRED_WHEEL_ENTRIES - entries)
    forbidden = sorted(
        entry
        for entry in entries
        if any(part in entry.split("/") for part in FORBIDDEN_WHEEL_PARTS)
        or entry.startswith(("build/", "dist/", "packaging/"))
    )
    if missing:
        raise ValueError(f"wheel is missing required resources: {missing}")
    if forbidden:
        raise ValueError(f"wheel contains forbidden files: {forbidden}")
    if seed.file_size < 1_000_000:
        raise ValueError(f"packaged seed database is unexpectedly small: {seed.file_size}")

    return WheelVerification(wheel=wheel, entry_count=len(entries), seed_bytes=seed.file_size)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _venv_python(venv_dir: Path) -> Path:
    executable = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        raise ReleaseCheckError(f"virtual environment Python was not created: {executable}")
    return executable


def _format_command(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


class ReleaseCheck:
    def __init__(self, repository_root: Path, log: TextIO):
        self.repository_root = repository_root.resolve()
        self.log = log
        self.dist_dir = self.repository_root / "dist"
        self.temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self.temporary_root: Path | None = None
        self.venv_dir: Path | None = None
        self.venv_python: Path | None = None
        self.outside_directory: Path | None = None
        self.profile_directory: Path | None = None
        self.default_profile_directory: Path | None = None
        self.server: subprocess.Popen[bytes] | None = None
        self.server_port: int | None = None

    def command(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        self.log.write(f"\n$ {_format_command(command)}\n")
        self.log.flush()
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.log.flush()
        if completed.returncode:
            raise ReleaseCheckError(
                f"command exited with code {completed.returncode}: {_format_command(command)}"
            )
        return completed

    def clean_and_build(self) -> WheelVerification:
        for path in (self.repository_root / "build", self.dist_dir):
            if path.exists():
                shutil.rmtree(path)
        for parent in (self.repository_root, self.repository_root / "src"):
            for path in parent.glob("*.egg-info"):
                if path.is_dir():
                    shutil.rmtree(path)

        build_available = subprocess.run(
            [sys.executable, "-c", "import build"],
            cwd=str(self.repository_root),
            stdout=self.log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if build_available.returncode:
            self.command(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "build",
                ],
                cwd=self.repository_root,
            )
        self.command(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--sdist",
                "--outdir",
                str(self.dist_dir),
            ],
            cwd=self.repository_root,
        )

        wheels = sorted(self.dist_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseCheckError(f"expected exactly one wheel after build, found {len(wheels)}")
        return WheelVerification(wheel=wheels[0].resolve(), entry_count=0, seed_bytes=0)

    @staticmethod
    def verify_package(wheel: WheelVerification) -> WheelVerification:
        try:
            return verify_wheel(wheel.wheel)
        except ValueError as exc:
            raise ReleaseCheckError(str(exc)) from exc

    def create_clean_environment(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="jobpicky-release-")
        self.temporary_root = Path(self.temporary_directory.name).resolve()
        self.outside_directory = self.temporary_root / "outside"
        self.venv_dir = self.temporary_root / "venv"
        self.profile_directory = self.temporary_root / "profile"
        self.default_profile_directory = self.temporary_root / "default-profile"
        self.outside_directory.mkdir()
        if self.repository_root == self.outside_directory or self.repository_root in self.outside_directory.parents:
            raise ReleaseCheckError("temporary launch directory is inside the repository")

        self.command([sys.executable, "-m", "venv", "--clear", str(self.venv_dir)])
        self.venv_python = _venv_python(self.venv_dir)

    def install_package(self, wheel: WheelVerification) -> None:
        if self.venv_python is None or self.outside_directory is None:
            raise ReleaseCheckError("clean environment is not ready")
        self.command(
            [
                str(self.venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel.wheel),
            ],
            cwd=self.outside_directory,
        )

    def dependency_check(self) -> None:
        if self.venv_python is None:
            raise ReleaseCheckError("clean environment is not ready")
        self.command([str(self.venv_python), "-m", "pip", "check"])

    def _installed_environment(self) -> dict[str, str]:
        if self.default_profile_directory is None:
            raise ReleaseCheckError("clean environment is not ready")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["JOBPICKY_HOME"] = str(self.default_profile_directory)
        return environment

    def launch_outside_repository(self) -> None:
        if self.venv_python is None or self.outside_directory is None or self.profile_directory is None:
            raise ReleaseCheckError("clean environment is not ready")

        import_check = [
            str(self.venv_python),
            "-c",
            (
                "import pathlib, sys, jobpicky; "
                "package = pathlib.Path(jobpicky.__file__).resolve(); "
                "repository = pathlib.Path(sys.argv[1]).resolve(); "
                "assert repository != package and repository not in package.parents, "
                "f'imported repository source: {package}'"
            ),
            str(self.repository_root),
        ]
        self.command(import_check, cwd=self.outside_directory, environment=self._installed_environment())

        port = _free_port()
        command = [
            str(self.venv_python),
            "-m",
            "jobpicky",
            "--no-browser",
            "--data-dir",
            str(self.profile_directory),
            "--port",
            str(port),
        ]
        self.log.write(f"\n$ {_format_command(command)}\n")
        self.log.flush()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.server = subprocess.Popen(
            command,
            cwd=str(self.outside_directory),
            env=self._installed_environment(),
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self.server_port = port
        time.sleep(0.2)
        if self.server.poll() is not None:
            raise ReleaseCheckError(f"WebUI exited during launch with code {self.server.returncode}")

    @staticmethod
    def _get(url: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, response.read()

    def webui_health_check(self) -> None:
        if self.server is None or self.server_port is None or self.profile_directory is None:
            raise ReleaseCheckError("WebUI was not launched")
        if self.outside_directory is None or self.repository_root in self.outside_directory.parents:
            raise ReleaseCheckError("WebUI was not launched outside the repository")

        health_url = f"http://127.0.0.1:{self.server_port}/api/health"
        page_url = f"http://127.0.0.1:{self.server_port}/"
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise ReleaseCheckError(f"WebUI exited before becoming ready with code {self.server.returncode}")
            try:
                health_status, health_body = self._get(health_url)
                page_status, page_body = self._get(page_url)
                health = json.loads(health_body)
                if health_status != 200 or page_status != 200:
                    raise ValueError(f"HTTP status health={health_status}, page={page_status}")
                if not isinstance(health, dict) or "job_count" not in health:
                    raise ValueError("health response does not contain job_count")
                if b"<!doctype html>" not in page_body.lower():
                    raise ValueError("homepage response is not HTML")
                expected_directories = (
                    self.profile_directory,
                    self.profile_directory / "logs",
                    self.profile_directory / "exports",
                    self.profile_directory / "backups",
                )
                missing = [str(path) for path in expected_directories if not path.is_dir()]
                if missing:
                    raise ValueError(f"runtime directories were not created: {missing}")
                if not (self.profile_directory / "jobs.sqlite").is_file():
                    raise ValueError("database was not created in the profile directory")
                return
            except (OSError, urllib.error.URLError, ValueError) as exc:
                last_error = exc
                time.sleep(0.25)
        raise ReleaseCheckError(f"WebUI did not become healthy: {last_error}")

    def _uvx_executable(self) -> Path:
        candidates: list[Path] = []
        discovered = shutil.which("uvx")
        if discovered:
            candidates.append(Path(discovered))
        candidates.append(Path(sys.executable).resolve().parent / ("uvx.exe" if os.name == "nt" else "uvx"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        self.command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "uv",
            ],
            cwd=self.repository_root,
        )
        discovered = shutil.which("uvx")
        if discovered:
            return Path(discovered)
        candidate = Path(sys.executable).resolve().parent / ("uvx.exe" if os.name == "nt" else "uvx")
        if candidate.is_file():
            return candidate
        raise ReleaseCheckError("uvx was not available after installing uv")

    def uvx_launch_smoke(self, wheel: WheelVerification) -> None:
        if self.temporary_root is None or self.outside_directory is None:
            raise ReleaseCheckError("clean environment is not ready")

        uvx = self._uvx_executable()
        profile_directory = self.temporary_root / "uvx-profile"
        port = _free_port()
        command = [
            str(uvx),
            "--python",
            "3.12",
            "--from",
            str(wheel.wheel),
            "jobpicky",
            "--no-browser",
            "--data-dir",
            str(profile_directory),
            "--port",
            str(port),
        ]
        self.log.write(f"\n$ {_format_command(command)}\n")
        self.log.flush()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=str(self.outside_directory),
            env=self._installed_environment(),
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        try:
            deadline = time.monotonic() + 45
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ReleaseCheckError(f"uvx WebUI exited during launch with code {process.returncode}")
                try:
                    health_status, health_body = self._get(f"http://127.0.0.1:{port}/api/health")
                    page_status, page_body = self._get(f"http://127.0.0.1:{port}/")
                    health = json.loads(health_body)
                    if health_status != 200 or page_status != 200:
                        raise ValueError(f"HTTP status health={health_status}, page={page_status}")
                    if not isinstance(health, dict) or "job_count" not in health:
                        raise ValueError("uvx health response does not contain job_count")
                    if b"<!doctype html>" not in page_body.lower():
                        raise ValueError("uvx homepage response is not HTML")
                    expected_directories = (
                        profile_directory,
                        profile_directory / "logs",
                        profile_directory / "exports",
                        profile_directory / "backups",
                    )
                    missing = [str(path) for path in expected_directories if not path.is_dir()]
                    if missing:
                        raise ValueError(f"uvx runtime directories were not created: {missing}")
                    if not (profile_directory / "jobs.sqlite").is_file():
                        raise ValueError("uvx database was not created in the profile directory")
                    return
                except (OSError, urllib.error.URLError, ValueError) as exc:
                    last_error = exc
                    time.sleep(0.25)
            raise ReleaseCheckError(f"uvx WebUI did not become healthy: {last_error}")
        finally:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                elif process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if os.name == "nt":
                time.sleep(0.5)

    def clean_shutdown(self) -> None:
        if self.server is not None:
            if self.server.poll() is None:
                if os.name == "nt":
                    self.server.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.server.terminate()
                try:
                    self.server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.server.kill()
                    self.server.wait(timeout=5)
                    raise ReleaseCheckError("WebUI did not stop within 10 seconds")

            if self.server.returncode not in (0, None):
                expected_signal_exit = 3 if os.name == "nt" else -signal.SIGTERM
                if self.server.returncode != expected_signal_exit:
                    raise ReleaseCheckError(f"WebUI did not exit cleanly: code {self.server.returncode}")

        temporary_directory = self.temporary_directory
        temporary_root = self.temporary_root
        if temporary_directory is not None:
            temporary_directory.cleanup()
        if temporary_root is not None and temporary_root.exists():
            raise ReleaseCheckError(f"temporary environment was not removed: {temporary_root}")

    def emergency_cleanup(self) -> None:
        if self.server is not None and self.server.poll() is None:
            try:
                if os.name == "nt":
                    self.server.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.server.terminate()
                self.server.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.server.kill()
                    self.server.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()


def _run_stage(name: str, action: Callable[[], object], passed: list[str]) -> None:
    action()
    passed.append(name)


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    results_directory = repository_root / ".test-results"
    log_path = results_directory / "release-check.log"
    results_directory.mkdir(parents=True, exist_ok=True)

    passed: list[str] = []
    failed_stage: str | None = None
    failure: Exception | None = None
    checker = None
    built_wheel: WheelVerification | None = None
    verified_wheel: WheelVerification | None = None

    with log_path.open("w", encoding="utf-8", errors="replace", buffering=1) as log:
        log.write(f"Release check started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Repository: {repository_root}\n")
        checker = ReleaseCheck(repository_root, log)
        try:
            built_wheel = checker.clean_and_build()
            passed.append("Build package")
        except Exception as exc:
            failed_stage, failure = "Build package", exc

        if failed_stage is None:
            try:
                if built_wheel is None:
                    raise ReleaseCheckError("build did not produce a wheel")
                verified_wheel = checker.verify_package(built_wheel)
                passed.append("Verify wheel")
            except Exception as exc:
                failed_stage, failure = "Verify wheel", exc

        if failed_stage is None:
            try:
                _run_stage("Create clean environment", checker.create_clean_environment, passed)
            except Exception as exc:
                failed_stage, failure = "Create clean environment", exc

        if failed_stage is None:
            try:
                if verified_wheel is None:
                    raise ReleaseCheckError("wheel verification did not produce a result")
                checker.install_package(verified_wheel)
                passed.append("Install package")
            except Exception as exc:
                failed_stage, failure = "Install package", exc

        if failed_stage is None:
            try:
                _run_stage("Dependency check", checker.dependency_check, passed)
            except Exception as exc:
                failed_stage, failure = "Dependency check", exc

        if failed_stage is None:
            try:
                _run_stage("Launch outside repository", checker.launch_outside_repository, passed)
            except Exception as exc:
                failed_stage, failure = "Launch outside repository", exc

        if failed_stage is None:
            try:
                _run_stage("WebUI health check", checker.webui_health_check, passed)
            except Exception as exc:
                failed_stage, failure = "WebUI health check", exc

        if failed_stage is None:
            try:
                if verified_wheel is None:
                    raise ReleaseCheckError("wheel verification did not produce a result")
                _run_stage("uvx launch smoke", lambda: checker.uvx_launch_smoke(verified_wheel), passed)
            except Exception as exc:
                failed_stage, failure = "uvx launch smoke", exc

        if failed_stage is None:
            try:
                _run_stage("Clean shutdown", checker.clean_shutdown, passed)
            except Exception as exc:
                failed_stage, failure = "Clean shutdown", exc

        if failed_stage is not None and failure is not None:
            log.write("\nFailure traceback:\n")
            traceback.print_exception(failure, file=log)
            try:
                checker.emergency_cleanup()
            except Exception as cleanup_error:
                log.write("\nEmergency cleanup failed:\n")
                traceback.print_exception(cleanup_error, file=log)

    if failed_stage is not None and failure is not None:
        reason = " ".join(str(failure).split()) or failure.__class__.__name__
        print(f"[FAIL] {failed_stage}")
        print(f"Reason: {reason}")
        print("Log: .test-results/release-check.log")
        return 1

    for stage in STAGES:
        print(f"[PASS] {stage}")
    print(f"\nRESULT: PASS  {len(passed)}/{len(STAGES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
