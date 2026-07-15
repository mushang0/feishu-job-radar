from pathlib import Path

from fastapi.testclient import TestClient

from jobpicky.models import Job
from jobpicky.paths import AppPaths
from jobpicky.storage import JobRepository
from jobpicky.web.app import create_app


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
    jobs = client.get("/api/jobs").json()
    assert jobs["items"][0]["company"] == "示例公司"
    assert jobs["total"] == 1
    assert jobs["recommended_total"] == 0
    page = client.get("/").text
    assert "JobPicky" in page
    assert "Your personalized job radar" in page
    assert "懂你偏好的个性化岗位雷达" in page
    assert "四步" not in page  # Product copy stays user-facing, not implementation-facing.
    assert 'href="/static/css/app.css?v=' in page
    assert 'src="/static/js/app.js?v=' in page
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_web_ui_exposes_local_first_product_structure(tmp_path: Path):
    client = TestClient(create_app(AppPaths(tmp_path / "profile")))
    page = client.get("/").text

    assert "岗位雷达" in page
    assert "全部岗位" in page
    assert "求职偏好" in page
    assert "集成" in page
    assert "完成设置并开始首次扫描" in page
    assert 'aria-live="polite"' in page
    assert "选择使用方式" not in page


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

    assert not paths.database.exists()
    first = client.get("/api/setup/preview")
    second = client.get("/api/setup/preview")
    preview = second.json()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert preview["configured"] is True
    assert preview["table_name"] == "求职工作台"
    assert preview["baseline_items"] == 747
    assert not paths.database.exists()
