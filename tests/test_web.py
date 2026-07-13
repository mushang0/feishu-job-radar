from pathlib import Path

from fastapi.testclient import TestClient

from job_monitor.models import Job
from job_monitor.paths import AppPaths
from job_monitor.storage import JobRepository
from job_monitor.web.app import create_app


def test_web_preferences_never_return_app_secret_and_persist_user_inputs(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")
    client = TestClient(create_app(paths))

    response = client.put(
        "/api/preferences",
        json={
            "user_profile": {
                "graduate_years": ["2027届"],
                "batches": ["秋招"],
                "role_groups": ["硬件/嵌入式"],
            },
            "feishu": {
                "base_url": "https://example.feishu.cn/base/bascnToken",
                "app_id": "app-id",
                "app_secret": "secret-value",
            },
        },
    )

    assert response.status_code == 200
    assert "secret-value" not in response.text
    saved = client.get("/api/preferences").json()
    assert saved["user_profile"]["role_groups"] == ["硬件/嵌入式"]
    assert saved["feishu"]["configured"] is True


def test_web_lists_local_jobs_and_health(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")
    repo = JobRepository(paths.database)
    repo.init_schema()
    repo.upsert_job(Job(dedupe_key="web:1", company="示例公司", title="FPGA 工程师"))
    client = TestClient(create_app(paths))

    assert client.get("/api/health").json()["job_count"] == 1
    assert client.get("/api/jobs").json()[0]["company"] == "示例公司"
    assert "飞书求职雷达" in client.get("/").text


def test_web_setup_preview_describes_three_step_workspace_flow(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")
    client = TestClient(create_app(paths))
    client.put(
        "/api/preferences",
        json={
            "user_profile": {"graduate_years": ["2027届"], "batches": ["秋招"], "role_groups": ["硬件/嵌入式"]},
            "feishu": {
                "base_url": "https://example.feishu.cn/base/bascnToken",
                "app_id": "app-id",
                "app_secret": "secret-value",
            },
        },
    )

    preview = client.get("/api/setup/preview").json()

    assert preview["configured"] is True
    assert preview["table_name"] == "求职工作台"
    assert preview["baseline_items"] >= 0
