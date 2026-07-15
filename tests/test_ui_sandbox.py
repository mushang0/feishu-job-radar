from pathlib import Path

import pytest

from scripts import ui_sandbox


def test_sandbox_layout_keeps_runtime_state_under_root(tmp_path: Path):
    paths = ui_sandbox.sandbox_paths(tmp_path / "sandbox")

    assert paths["venv"].parent == paths["root"]
    assert paths["profile"].parent == paths["root"]
    assert paths["logs"].parent == paths["root"]


def test_safe_root_rejects_repository_and_external_paths(tmp_path: Path):
    with pytest.raises(SystemExit):
        ui_sandbox.ensure_safe_root(ui_sandbox.REPOSITORY_ROOT)
    with pytest.raises(SystemExit):
        ui_sandbox.ensure_safe_root(tmp_path)


def test_remove_sandbox_only_removes_selected_child(tmp_path: Path, monkeypatch):
    repository = tmp_path / "repo"
    sandbox = repository / ".test-results" / "ui-sandbox"
    keep = repository / "keep.txt"
    sandbox.mkdir(parents=True)
    (sandbox / "jobs.sqlite").write_bytes(b"test")
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(ui_sandbox, "REPOSITORY_ROOT", repository)

    ui_sandbox.remove_sandbox(sandbox)

    assert not sandbox.exists()
    assert keep.read_text(encoding="utf-8") == "keep"
