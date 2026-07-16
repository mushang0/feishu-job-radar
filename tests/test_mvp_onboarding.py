from pathlib import Path
from types import SimpleNamespace
from threading import Event
import time

from fastapi.testclient import TestClient

from jobpicky.config import load_config
from jobpicky.core import DatabaseBootstrapService
from jobpicky.matcher import Matcher
from jobpicky.models import Job
from jobpicky.paths import AppPaths
from jobpicky.pipeline import DailySummary
from jobpicky.services.scanning import DailyWorkflowResult
from jobpicky.services.synchronization import SyncSummary
from jobpicky.storage import JobRepository
from jobpicky.web.app import create_app


def _profile_payload():
    return {
        "user_profile": {
            "batches": ["秋招", "实习"],
            "role_groups": ["嵌入式", "FPGA"],
            "target_cities": ["上海"],
            "custom_keywords": ["AUTOSAR"],
            "selected_company_groups": ["org.internet_major"],
            "custom_companies": ["华为"],
            "graduate_years": [],
        }
    }


def test_onboarding_options_and_profile_save_do_not_require_feishu(tmp_path: Path):
    client = TestClient(create_app(AppPaths(tmp_path / "profile")))

    options = client.get("/api/onboarding/options")

    assert options.status_code == 200
    payload = options.json()
    values = {
        option["value"]
        for section in payload["role_sections"]
        for option in section["options"]
    }
    assert {"hardware.embedded", "hardware.circuit", "hardware.fpga", "electrical.power", "ai.algorithm", "security.cyber"} <= values
    assert payload["cities"][0] == {"value": "", "label": "不限"}
    assert any(section["value"] == "province:44" for section in payload["location_sections"])
    assert any(option["value"] == "org.research_institute" for option in payload["organization_groups"])

    saved = client.put("/api/preferences", json=_profile_payload())

    assert saved.status_code == 200
    assert saved.json()["onboarding_complete"] is True
    assert saved.json()["user_profile"]["custom_keywords"] == ["AUTOSAR"]
    assert saved.json()["user_profile"]["selected_company_groups"] == ["org.internet_major"]
    assert saved.json()["user_profile"]["custom_companies"] == ["华为"]
    assert saved.json()["feishu"]["configured"] is False


def test_local_start_runs_shared_workflow_without_feishu(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200
    calls = []

    def fake_local(service, **kwargs):
        calls.append(("local", service.config["user_profile"]["custom_keywords"]))
        from jobpicky.services.local import LocalInitializationResult
        return LocalInitializationResult(
            seeded=True,
            baseline_items=4,
            baseline_recommended_items=2,
            daily=DailyWorkflowResult(
            status="success",
            task_id=kwargs["task_id"],
            fetched_count=3,
            created_count=2,
            recommended_count=1,
            ),
        )

    monkeypatch.setattr("jobpicky.web.app.LocalApplicationService.initialize_and_update", fake_local)
    monkeypatch.setattr(
        "jobpicky.integrations.feishu.service.FeishuIntegrationService.test_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local mode must not call Feishu")),
    )

    response = client.post("/api/local/start")

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    for _ in range(100):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] not in {"queued", "running"}:
            break
        time.sleep(0.01)

    assert task["status"] == "success"
    assert task["mode"] == "local"
    assert task["seeded"] is True
    assert task["baseline_recommended_items"] == 2
    assert calls == [("local", ["AUTOSAR"])]


def test_scan_running_state_is_recoverable_and_duplicate_start_is_rejected(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200
    entered, release = Event(), Event()

    def slow_local(_service, **kwargs):
        from jobpicky.services.local import LocalInitializationResult
        entered.set()
        assert release.wait(timeout=5)
        return LocalInitializationResult(
            seeded=True,
            baseline_items=0,
            baseline_recommended_items=0,
            daily=DailyWorkflowResult(status="success", task_id=kwargs["task_id"]),
        )

    monkeypatch.setattr("jobpicky.web.app.LocalApplicationService.initialize_and_update", slow_local)
    first = client.post("/api/local/start")
    assert first.status_code == 202
    assert entered.wait(timeout=2)

    restored = client.get("/api/scan/status").json()
    assert restored["state"] == "running"
    assert restored["active_task"]["task_id"] == first.json()["task_id"]
    assert restored["active_task"]["started_at"]
    duplicate = client.post("/api/local/start")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "already_running"
    release.set()
    for _ in range(100):
        terminal = client.get(f"/api/tasks/{first.json()['task_id']}").json()
        if terminal["status"] not in {"queued", "running", "cancelling"}:
            break
        time.sleep(0.01)
    assert terminal["status"] == "success"
    restarted = TestClient(create_app(paths)).get("/api/scan/status").json()
    assert restarted["state"] == "success"
    assert restarted["last_run"]["task_id"] == first.json()["task_id"]


def test_feishu_test_initializes_workspace_and_syncs(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    DatabaseBootstrapService(paths.database).initialize()
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200
    calls = []

    class FeishuClient:
        def __init__(self, config):
            self.config = config
            calls.append(("client", config.app_id))

        def get_app(self):
            calls.append("get_app")
            return {"name": "Test Base"}

    class Provisioner:
        def __init__(self, _client, _schema):
            calls.append("provisioner")

        def provision(self, _table_id, *, on_table_created):
            calls.append("provision")
            on_table_created("tbl-managed")
            return SimpleNamespace(
                table_id="tbl-managed",
                workspace_url="https://example.feishu.cn/base/token?table=tbl-managed",
            )

    def test_connection(service):
        feishu_client = FeishuClient(SimpleNamespace(app_id=service.config["feishu"]["app_id"]))
        feishu_client.get_app()
        return feishu_client

    monkeypatch.setattr(
        "jobpicky.integrations.feishu.service.FeishuIntegrationService.test_connection",
        test_connection,
    )
    monkeypatch.setattr("jobpicky.integrations.feishu.service.WorkspaceProvisioner", Provisioner)
    monkeypatch.setattr(
        "jobpicky.services.initialization.sync_feishu",
        lambda repo, config, rows, **_kwargs: calls.append(("sync", rows))
        or SyncSummary(created=3, updated=1),
    )

    response = client.post(
        "/api/feishu/test",
        json={
            "base_url": "https://example.feishu.cn/base/bascnToken",
            "app_id": "app-id",
            "app_secret": "secret-value",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["table_id"] == "tbl-managed"
    assert payload["sync"] == {"created": 3, "updated": 1, "skipped": 0, "failed": 0}
    assert calls[0] == ("client", "app-id")
    assert calls.count("get_app") == 1
    assert "provision" in calls
    assert any(item[0] == "sync" for item in calls if isinstance(item, tuple))

    saved = client.get("/api/preferences").json()
    assert saved["feishu"]["configured"] is True
    assert saved["feishu"]["workspace_configured"] is True
    assert "secret-value" not in response.text


def test_feishu_connection_failure_does_not_save_credentials(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    DatabaseBootstrapService(paths.database).initialize()
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200

    class FailingClient:
        def __init__(self, _config):
            pass

        def get_app(self):
            raise RuntimeError("invalid secret")

    def fail_connection(service):
        client = FailingClient(service.config)
        client.get_app()

    monkeypatch.setattr(
        "jobpicky.integrations.feishu.service.FeishuIntegrationService.test_connection",
        fail_connection,
    )

    response = client.post(
        "/api/feishu/test",
        json={
            "base_url": "https://example.feishu.cn/base/bascnToken",
            "app_id": "app-id",
            "app_secret": "secret-value",
        },
    )

    assert response.status_code == 502
    assert "secret-value" not in response.text
    saved = client.get("/api/preferences").json()
    assert saved["feishu"]["configured"] is False


def test_feishu_test_requires_local_database_before_connection(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(
        "jobpicky.integrations.feishu.service.FeishuIntegrationService.test_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("connection must not run")),
    )

    response = client.post(
        "/api/feishu/test",
        json={"base_url": "https://example.feishu.cn/base/token", "app_id": "app-id", "app_secret": "secret-value"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "local_database_not_initialized"
    assert "请先完成本地初始化" in response.text
    assert not paths.database.exists()
    assert "secret-value" not in response.text


def test_feishu_test_rejects_empty_schema_without_remote_work(tmp_path: Path, monkeypatch):
    paths = AppPaths(tmp_path / "profile")
    JobRepository(paths.database).init_schema()
    client = TestClient(create_app(paths))
    assert client.put("/api/preferences", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(
        "jobpicky.integrations.feishu.service.FeishuIntegrationService.test_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("connection, provisioning and sync must not run")
        ),
    )

    response = client.post(
        "/api/feishu/test",
        json={"base_url": "https://example.feishu.cn/base/token", "app_id": "app-id", "app_secret": "secret-value"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "local_database_not_initialized"
    assert "请先完成本地初始化" in response.text
    assert JobRepository(paths.database).count_jobs() == 0
    assert "secret-value" not in response.text


def test_role_group_and_custom_keyword_expand_local_matching(tmp_path: Path):
    config = load_config(tmp_path / "missing.yaml")
    profile = config["user_profile"]
    profile.update(
        {
            "graduate_years": [],
            "batches": ["实习"],
            "role_groups": ["FPGA"],
            "target_cities": [],
            "custom_keywords": ["AUTOSAR"],
        }
    )
    matcher = Matcher(config)

    fpga_job = Job(
        company="示例公司",
        title="RTL 设计工程师",
        batch="实习",
        role_text="使用 Verilog 和 Vivado 完成 FPGA 开发",
    )
    custom_job = Job(
        company="示例公司",
        title="嵌入式软件工程师",
        batch="实习",
        role_text="负责 AUTOSAR 平台开发",
    )

    assert matcher.match(fpga_job).should_push is True
    assert matcher.match(custom_job).match_reason == "命中自定义关键词"
