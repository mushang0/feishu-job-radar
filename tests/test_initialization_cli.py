from pathlib import Path
from types import SimpleNamespace

from job_monitor.cli import _run_init
from job_monitor.pipeline import InitSummary


def _config():
    return {
        "user_profile": {"graduate_years": ["2027届"], "batches": ["秋招"], "role_groups": ["硬件/嵌入式"]},
        "feishu": {
            "base_url": "https://example.feishu.cn/base/bascnToken",
            "workspace_table_id": "",
            "workspace_schema_version": "",
            "app_id": "cli-app",
            "app_secret": "secret",
        },
    }


def test_run_init_orders_preflight_provision_scan_and_sync(tmp_path: Path, monkeypatch):
    events = []
    config = _config()

    class Client:
        def __init__(self, _config):
            events.append("client")

        def get_app(self):
            events.append("read-only-preflight")
            return {"name": "Base"}

        def list_tables(self):
            events.append("list-tables")
            return []

    class Provisioner:
        def __init__(self, client, schema):
            pass

        def provision(self, table_id, *, on_table_created):
            events.append("provision")
            on_table_created("tbl-managed")
            return SimpleNamespace(table_id="tbl-managed", workspace_url="https://example.feishu.cn/base/bascnToken?table=tbl-managed")

    class Crawler:
        def __init__(self, _config):
            assert "provision" in events
            events.append("crawler")

        def crawl_pages(self, mode):
            assert mode == "init"
            return []

    monkeypatch.setattr("job_monitor.cli.collect_missing_config", lambda value: value)
    monkeypatch.setattr("job_monitor.cli.confirm_initialization", lambda *args, **kwargs: events.append("confirm") or True)
    monkeypatch.setattr("job_monitor.cli.save_config", lambda value, path: events.append(f"save:{value['feishu'].get('workspace_table_id') or 'config'}"))
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)
    monkeypatch.setattr("job_monitor.cli.WorkspaceProvisioner", Provisioner)
    monkeypatch.setattr("job_monitor.cli.WonderCVCrawler", Crawler)
    monkeypatch.setattr(
        "job_monitor.cli.run_init_with_page_batches",
        lambda *args, **kwargs: events.append("scan") or InitSummary(0, 0, 0, 0, 0, 0),
    )
    monkeypatch.setattr("job_monitor.cli._sync_feishu", lambda *args, **kwargs: events.append("sync") or SimpleNamespace(created=0, updated=0, skipped=0, failed=0))

    code = _run_init(config, str(tmp_path / "jobs.sqlite"), str(tmp_path / "config.yaml"), str(tmp_path / "export.xlsx"), assume_yes=True)

    assert code == 0
    assert events.index("read-only-preflight") < events.index("confirm") < events.index("provision") < events.index("crawler") < events.index("scan") < events.index("sync")
    assert config["feishu"]["workspace_table_id"] == "tbl-managed"
    assert config["feishu"]["workspace_schema_version"] == "2"


def test_run_init_stops_before_crawler_when_provisioning_fails(tmp_path: Path, monkeypatch):
    config = _config()

    class Client:
        def __init__(self, _config):
            pass

        def get_app(self):
            return {"name": "Base"}

        def list_tables(self):
            return []

    class Provisioner:
        def __init__(self, client, schema):
            pass

        def provision(self, table_id, *, on_table_created):
            raise RuntimeError("permission denied")

    class Crawler:
        def __init__(self, _config):
            raise AssertionError("crawler must not start")

    monkeypatch.setattr("job_monitor.cli.collect_missing_config", lambda value: value)
    monkeypatch.setattr("job_monitor.cli.confirm_initialization", lambda *args, **kwargs: True)
    monkeypatch.setattr("job_monitor.cli.save_config", lambda *args, **kwargs: None)
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)
    monkeypatch.setattr("job_monitor.cli.WorkspaceProvisioner", Provisioner)
    monkeypatch.setattr("job_monitor.cli.WonderCVCrawler", Crawler)

    code = _run_init(config, str(tmp_path / "jobs.sqlite"), str(tmp_path / "config.yaml"), str(tmp_path / "export.xlsx"), assume_yes=True)

    assert code == 1


def test_run_init_decline_performs_no_remote_write(tmp_path: Path, monkeypatch):
    config = _config()

    class Client:
        def __init__(self, _config):
            pass

        def get_app(self):
            return {"name": "Base"}

        def list_tables(self):
            return []

    class Provisioner:
        def __init__(self, client, schema):
            raise AssertionError("provisioner must not be constructed")

    monkeypatch.setattr("job_monitor.cli.collect_missing_config", lambda value: value)
    monkeypatch.setattr("job_monitor.cli.confirm_initialization", lambda *args, **kwargs: False)
    monkeypatch.setattr("job_monitor.cli.save_config", lambda *args, **kwargs: None)
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)
    monkeypatch.setattr("job_monitor.cli.WorkspaceProvisioner", Provisioner)

    assert _run_init(config, str(tmp_path / "jobs.sqlite"), str(tmp_path / "config.yaml"), str(tmp_path / "export.xlsx"), assume_yes=False) == 0


def test_read_only_preflight_checks_saved_workspace_resources():
    from job_monitor.cli import _read_only_workspace_preflight

    calls = []

    class Client:
        def list_tables(self):
            return [{"table_id": "tbl-managed", "name": "求职工作台"}]

        def list_fields(self, table_id):
            calls.append(("fields", table_id))
            return []

        def list_views(self, table_id):
            calls.append(("views", table_id))
            return []

        def list_all_records(self, table_id):
            calls.append(("records", table_id))
            return []

    _read_only_workspace_preflight(Client(), {"feishu": {"workspace_table_id": "tbl-managed"}})

    assert calls == [
        ("fields", "tbl-managed"),
        ("views", "tbl-managed"),
        ("records", "tbl-managed"),
    ]
