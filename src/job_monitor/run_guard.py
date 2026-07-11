from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


class DailyRunInProgress(RuntimeError):
    pass


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows;
        # it maps to TerminateProcess.  Open a query-only handle instead.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_shell_ancestor() -> int | None:
    """Return the nearest cmd/PowerShell ancestor without adding a dependency."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    processes: dict[int, tuple[int, str]] = {}
    entry = Entry(dwSize=ctypes.sizeof(Entry))
    try:
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                processes[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
                entry.dwSize = ctypes.sizeof(Entry)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    pid = os.getppid()
    while pid and pid in processes:
        parent, executable = processes[pid]
        if executable in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
            return pid
        pid = parent
    return None


class DailyRunGuard:
    """Prevent concurrent daily runs and stop when the launching shell disappears."""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).with_suffix(".daily.lock")
        self.cancelled = threading.Event()
        self._watcher: threading.Thread | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                try:
                    owner = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(owner.get("pid", 0))
                except (OSError, ValueError, json.JSONDecodeError):
                    pid = 0
                if _pid_is_running(pid):
                    raise DailyRunInProgress("已有日常扫描正在运行，请等待其完成后再试")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "started_at": time.time()}, stream)
            break
        else:
            raise DailyRunInProgress("无法获取日常扫描运行锁")

        if os.environ.get("JOB_MONITOR_WATCH_PARENT") == "1":
            try:
                parent_pid = int(os.environ.get("JOB_MONITOR_PARENT_PID", ""))
            except ValueError:
                parent_pid = None
            parent_pid = parent_pid or _windows_shell_ancestor()
            if parent_pid:
                self._watcher = threading.Thread(target=self._watch_parent, args=(parent_pid,), daemon=True)
                self._watcher.start()
        return self

    def _watch_parent(self, parent_pid: int) -> None:
        while not self.cancelled.is_set():
            if not _pid_is_running(parent_pid):
                self.cancelled.set()
                return
            time.sleep(0.5)

    def __exit__(self, *_args) -> None:
        self.cancelled.set()
        self.path.unlink(missing_ok=True)
