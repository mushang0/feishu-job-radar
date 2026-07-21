import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jobpicky.config import load_config
from jobpicky.core import DatabaseBootstrapService
from jobpicky.feishu import FeishuApiError
from jobpicky.integrations.feishu import FeishuIntegrationService, FeishuPreflightResult
from jobpicky.paths import AppPaths
from jobpicky.services.synchronization import SyncSummary
from jobpicky.storage import JobRepository
from jobpicky.web.app import create_app


def configured_client(tmp_path: Path) -> tuple[AppPaths, TestClient]:
    paths = AppPaths(tmp_path / "profile")
    DatabaseBootstrapService(paths.database).initialize()
    client = TestClient(create_app(paths))
    response = client.put(
        "/api/preferences",
        json={"user_profile": {"batches": ["秋招"], "role_groups": ["hardware.embedded"]}},
    )
    assert response.status_code == 200
    return paths, client


def payload(base_url="https://example.feishu.cn/base/bascnGuide"):
    return {"base_url": base_url, "app_id": "cli_guide", "app_secret": "session-only-secret"}


def test_preflight_is_read_only_and_does_not_save_credentials(tmp_path: Path, monkeypatch):
    paths, client = configured_client(tmp_path)
    calls = []

    def fake_preflight(service):
        calls.append((service.config["feishu"]["app_id"], service.repo.count_jobs()))
        return FeishuPreflightResult("求职测试 Base", "求职工作台", service.repo.count_jobs(), 0)

    monkeypatch.setattr(FeishuIntegrationService, "preflight", fake_preflight)
    response = client.post("/api/feishu/preflight", json=payload())

    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["base_name"] == "求职测试 Base"
    assert calls and calls[0][0] == "cli_guide"
    saved = load_config(paths.config)["feishu"]
    assert saved["app_id"] == ""
    assert saved["app_secret"] == ""


def test_service_preflight_calls_only_read_api(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()

    class ReadOnlyClient:
        def __init__(self, config):
            self.config = config

        def get_app(self):
            return {"name": "只读测试 Base"}

        def __getattr__(self, name):
            raise AssertionError(f"preflight must not call {name}")

    service = FeishuIntegrationService(
        repo,
        {"feishu": payload()},
        client_factory=ReadOnlyClient,
    )

    result = service.preflight()

    assert result.base_name == "只读测试 Base"
    assert result.write_access_confirmed is False


def test_preflight_rejects_wiki_link_with_actionable_message(tmp_path: Path):
    _, client = configured_client(tmp_path)
    response = client.post(
        "/api/feishu/preflight",
        json=payload("https://example.feishu.cn/wiki/wikcnGuide"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_base_url"
    assert "/base/" in response.text


def test_preflight_classifies_permission_and_service_errors(tmp_path: Path, monkeypatch):
    _, client = configured_client(tmp_path)

    monkeypatch.setattr(
        FeishuIntegrationService,
        "preflight",
        lambda _service: (_ for _ in ()).throw(FeishuApiError("permission denied", code=1254302)),
    )
    denied = client.post("/api/feishu/preflight", json=payload())
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "base_access_denied"

    monkeypatch.setattr(
        FeishuIntegrationService,
        "preflight",
        lambda _service: (_ for _ in ()).throw(FeishuApiError("temporary", retryable=True)),
    )
    unavailable = client.post("/api/feishu/preflight", json=payload())
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "feishu_service_unavailable"


def test_connect_saves_and_returns_complete_sync_result(tmp_path: Path, monkeypatch):
    paths, client = configured_client(tmp_path)
    calls = []
    fake_client = object()
    monkeypatch.setattr(FeishuIntegrationService, "test_connection", lambda _service: calls.append("validate") or fake_client)

    def initialize(_service, config, *, client=None):
        calls.append(("connect", client, config["feishu"]["app_id"]))
        return SimpleNamespace(
            table_id="tbl-guide",
            workspace_url="https://example.feishu.cn/base/bascnGuide?table=tbl-guide",
            baseline_items=811,
            recommended_items=17,
            sync=SyncSummary(created=12, updated=3, skipped=2, failed=1),
        )

    monkeypatch.setattr("jobpicky.services.initialization.InitializationService.initialize", initialize)
    response = client.post("/api/feishu/connect", json=payload())

    assert response.status_code == 200
    result = response.json()
    assert result["workspace_url"].endswith("table=tbl-guide")
    assert (result["created"], result["updated"], result["skipped"], result["failed"]) == (12, 3, 2, 1)
    assert result["partial_failure"] is True
    assert calls[0] == "validate"
    assert calls[1][0] == "connect"
    assert load_config(paths.config)["feishu"]["app_secret"] == "session-only-secret"
    assert "session-only-secret" not in response.text


def test_status_never_returns_secrets_and_disconnect_is_explicit(tmp_path: Path):
    paths, client = configured_client(tmp_path)
    config = load_config(paths.config)
    config["feishu"].update(payload())
    config["feishu"].update({"workspace_table_id": "tbl-guide", "workspace_url": "https://example.feishu.cn/base/bascnGuide?table=tbl-guide"})
    from jobpicky.config import save_config

    save_config(config, paths.config)
    status = client.get("/api/feishu/status")
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert "app_secret" not in status.text
    assert "session-only-secret" not in status.text

    kept = client.post("/api/feishu/disconnect", json={"clear_credentials": False}).json()
    assert kept["configured"] is False
    assert load_config(paths.config)["feishu"]["app_secret"] == "session-only-secret"

    client.post("/api/feishu/disconnect", json={"clear_credentials": True})
    assert load_config(paths.config)["feishu"]["app_secret"] == ""


def test_nine_step_ui_security_accessibility_and_assets(tmp_path: Path):
    _, client = configured_client(tmp_path)
    page = client.get("/").text
    script = client.get("/static/js/app.js").text
    style = client.get("/static/css/app.css").text
    manifest = json.loads(Path("docs/feishu-guide/screenshot-manifest.json").read_text(encoding="utf-8"))

    assert page.count("data-feishu-step=") == 9
    assert 'target="_blank" rel="noopener noreferrer"' in page
    assert "https://open.feishu.cn/app" in page
    assert "将推荐岗位同步到你的飞书多维表格，并每日更新新增岗位。" in page
    assert "https://www.feishu.cn/product/base" in page
    assert 'id="base-new-guide"' in page and 'id="base-existing-guide"' in page
    assert "新建一份空白多维表格" in page
    assert "版本管理与发布" in page
    assert "最终的空白表格样子" in page
    assert "多维表格已创建，下一步" in script
    assert "已打开目标 Base，下一步" in script
    assert "bitable:app" in page
    assert "发送每日提醒" not in page
    assert 'id="feishu-back"' in page and 'id="feishu-next"' in page
    assert "jobpicky.feishuGuideStep" in script
    assert 'localStorage.setItem("jobpicky.feishuGuideStep"' in script
    assert "localStorage.setItem(\"app-secret\"" not in script
    assert "app_secret" not in script.split("localStorage.setItem", 1)[-1].split("function renderFeishuStatus", 1)[0]
    assert "partial_failure" in script and "同步部分完成" in script
    assert "prefers-reduced-motion:reduce" in style
    assert len(manifest) == 18
    for item in manifest:
        assert item["altText"]
        assert f'alt="{item["altText"]}"' in page
        image = Path("src/jobpicky/web/static/images/feishu-guide") / item["file"]
        assert image.is_file() and image.stat().st_size > 1000
