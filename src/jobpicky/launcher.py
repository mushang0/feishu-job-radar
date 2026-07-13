from __future__ import annotations

import argparse
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .paths import AppPaths
from .services.migration import migrate_legacy_project
from .web.app import create_app


def find_free_port(host: str = "127.0.0.1", start: int = 8765, attempts: int = 20) -> int:
    for port in range(start, start + max(1, attempts)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"无法在 {host}:{start}-{start + attempts - 1} 找到可用端口")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobpicky")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 表示自动选择可用端口")
    parser.add_argument("--data-dir", type=Path, help="开发/迁移用数据目录；普通用户无需设置")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    paths = AppPaths(args.data_dir.resolve()) if args.data_dir else AppPaths.default()
    paths.ensure_runtime_directories()
    if not args.data_dir and not paths.migration_state.exists():
        migrate_legacy_project(AppPaths.legacy_project(Path.cwd()), paths)
    port = args.port or find_free_port(args.host)
    url = f"http://{args.host}:{port}/"
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(paths), host=args.host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
