"""Create and run an isolated, repeatable JobPicky UI test installation."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SANDBOX = REPOSITORY_ROOT / ".test-results" / "ui-sandbox"


def sandbox_paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "venv": root / "venv",
        "profile": root / "profile",
        "logs": root / "logs",
    }


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_safe_root(root: Path) -> Path:
    root = root.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if root == repository or repository not in root.parents:
        raise SystemExit("沙盒目录必须位于仓库内部，且不能是仓库根目录。")
    return root


def remove_sandbox(root: Path) -> None:
    root = ensure_safe_root(root)
    if root.exists():
        shutil.rmtree(root)


def create_fresh_install(paths: dict[str, Path]) -> None:
    remove_sandbox(paths["root"])
    paths["root"].mkdir(parents=True)
    print(f"[1/3] 创建隔离虚拟环境：{paths['venv']}", flush=True)
    subprocess.run([sys.executable, "-m", "venv", str(paths["venv"])], check=True)
    python = venv_python(paths["venv"])
    print("[2/3] 从当前源码构建并安装独立副本…", flush=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(REPOSITORY_ROOT)],
        cwd=paths["root"], check=True,
    )
    paths["profile"].mkdir()
    paths["logs"].mkdir()
    (paths["root"] / "INSTALL_SOURCE.txt").write_text(
        f"source={REPOSITORY_ROOT}\npython={sys.executable}\n",
        encoding="utf-8",
    )
    print("[3/3] 全新沙盒安装完成。", flush=True)


def require_install(paths: dict[str, Path]) -> Path:
    python = venv_python(paths["venv"])
    if not python.is_file():
        raise SystemExit("尚无可继续的沙盒。请先运行：python scripts/ui_sandbox.py fresh")
    return python


def available_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"端口 {preferred}-{preferred + 19} 均被占用。")


def run_ui(paths: dict[str, Path], *, port: int, no_browser: bool) -> int:
    python = require_install(paths)
    selected_port = available_port(port)
    url = f"http://127.0.0.1:{selected_port}/"
    print(f"沙盒数据：{paths['profile']}", flush=True)
    print(f"测试地址：{url}", flush=True)
    print("按 Ctrl+C 停止；数据会保留供 continue 使用。", flush=True)
    command = [str(python), "-m", "jobpicky.launcher", "--data-dir", str(paths["profile"]), "--port", str(selected_port)]
    if no_browser:
        command.append("--no-browser")
    try:
        return subprocess.run(command, cwd=paths["root"]).returncode
    except KeyboardInterrupt:
        return 130


def print_status(paths: dict[str, Path]) -> None:
    installed = venv_python(paths["venv"]).is_file()
    profile = paths["profile"]
    print(f"沙盒目录：{paths['root']}")
    print(f"安装状态：{'可用' if installed else '未创建'}")
    print(f"配置文件：{'存在' if (profile / 'config.yaml').is_file() else '不存在'}")
    database = profile / "jobs.sqlite"
    print(f"数据库：{'存在' if database.is_file() else '不存在'}")
    if database.is_file():
        print(f"数据库大小：{database.stat().st_size / 1024 / 1024:.1f} MiB")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JobPicky 隔离 UI 测试沙盒")
    parser.add_argument("action", choices=("fresh", "continue", "status", "clean"))
    parser.add_argument("--port", type=int, default=8877, help="首选端口；占用时自动尝试后续 19 个端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--root", type=Path, default=DEFAULT_SANDBOX, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = ensure_safe_root(args.root)
    paths = sandbox_paths(root)
    if args.action == "clean":
        remove_sandbox(root)
        print(f"已删除沙盒：{root}")
        return 0
    if args.action == "status":
        print_status(paths)
        return 0
    if args.action == "fresh":
        create_fresh_install(paths)
    return run_ui(paths, port=args.port, no_browser=args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
