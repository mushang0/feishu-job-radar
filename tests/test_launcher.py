import socket
from pathlib import Path

from jobpicky.launcher import find_free_port


def test_find_free_port_skips_a_bound_port():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    try:
        blocked = occupied.getsockname()[1]
        selected = find_free_port(start=blocked, attempts=3)
        assert selected != blocked
    finally:
        occupied.close()


def test_launcher_passes_local_app_to_uvicorn_without_opening_browser(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run(app, host, port, log_level):
        captured.update({"app": app, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr("jobpicky.launcher.uvicorn.run", fake_run)
    monkeypatch.setattr("jobpicky.launcher.webbrowser.open", lambda *_args: (_ for _ in ()).throw(AssertionError("browser should be disabled")))

    from jobpicky.launcher import main

    assert main(["--data-dir", str(tmp_path / "profile"), "--port", "8877", "--no-browser"]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8877
    assert captured["app"].title == "JobPicky"


def test_launcher_opens_browser_by_default(tmp_path: Path, monkeypatch):
    opened = []

    class ImmediateTimer:
        def __init__(self, _delay, function, args=()):
            self.function = function
            self.args = args

        def start(self):
            self.function(*self.args)

    monkeypatch.setattr("jobpicky.launcher.threading.Timer", ImmediateTimer)
    monkeypatch.setattr("jobpicky.launcher.webbrowser.open", opened.append)
    monkeypatch.setattr("jobpicky.launcher.uvicorn.run", lambda *args, **kwargs: None)

    from jobpicky.launcher import main

    assert main(["--data-dir", str(tmp_path / "profile"), "--port", "8878"]) == 0
    assert opened == ["http://127.0.0.1:8878/"]
