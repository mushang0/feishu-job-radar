from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=2) as response:
        return response.status, response.read()


def main() -> int:
    import job_monitor

    package_path = Path(job_monitor.__file__).resolve()
    repository_root = Path(__file__).resolve().parents[1]
    if package_path == repository_root or repository_root in package_path.parents:
        raise RuntimeError(f"smoke test imported job_monitor from the repository: {package_path}")

    with tempfile.TemporaryDirectory(prefix="feishu-job-radar-smoke-") as temporary:
        root = Path(temporary).resolve()
        outside = root / "outside"
        profile = root / "profile"
        outside.mkdir()
        port = free_port()
        command = [
            sys.executable,
            "-m",
            "job_monitor",
            "--no-browser",
            "--data-dir",
            str(profile),
            "--port",
            str(port),
        ]
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["FEISHU_JOB_RADAR_HOME"] = str(root / "default-profile")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=outside,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        try:
            last_error: Exception | None = None
            for _ in range(80):
                if process.poll() is not None:
                    break
                try:
                    health_status, health_body = get(f"http://127.0.0.1:{port}/api/health")
                    page_status, page_body = get(f"http://127.0.0.1:{port}/")
                    health = json.loads(health_body)
                    if health_status != 200 or page_status != 200:
                        raise RuntimeError("WebUI returned a non-200 response")
                    if "job_count" not in health or "飞书求职雷达".encode() not in page_body:
                        raise RuntimeError("WebUI smoke response is incomplete")
                    print(
                        f"installed WebUI smoke passed: cwd={outside}; "
                        f"package={package_path}; health={health_status}; "
                        f"page={page_status}; pid={process.pid}"
                    )
                    return 0
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.25)
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(
                f"installed WebUI did not become ready: {last_error}; "
                f"exit={process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
            )
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.returncode not in (0, None):
                stdout, stderr = process.communicate()
                windows_graceful_break = (
                    os.name == "nt"
                    and process.returncode == 3
                    and "Application shutdown complete" in stderr
                    and "Finished server process" in stderr
                )
                if not windows_graceful_break:
                    raise RuntimeError(
                        f"installed WebUI did not exit cleanly: exit={process.returncode}; "
                        f"stdout={stdout!r}; stderr={stderr!r}"
                    )
                print("installed WebUI completed graceful Windows CTRL_BREAK shutdown")


if __name__ == "__main__":
    raise SystemExit(main())
