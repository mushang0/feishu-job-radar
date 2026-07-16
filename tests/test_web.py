from pathlib import Path
from datetime import datetime, timedelta

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
    assert saved["user_profile"]["role_groups"] == ["hardware.embedded"]
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
    assert "Your personalized job radar" not in page
    assert "懂你偏好的个性化岗位雷达" not in page
    assert "建立你的岗位雷达" in page
    assert "四步" not in page  # Product copy stays user-facing, not implementation-facing.
    assert 'href="/static/css/app.css?v=' in page
    assert 'src="/static/js/app.js?v=' in page
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_web_ui_exposes_local_first_product_structure(tmp_path: Path):
    client = TestClient(create_app(AppPaths(tmp_path / "profile")))
    page = client.get("/").text
    script = client.get("/static/js/app.js").text

    assert "岗位雷达" in page
    assert "全部岗位" in page
    assert "集成" in page
    assert 'data-route="preferences"' not in page
    assert 'data-route="jobs"' not in page
    assert '<a href="#jobs" class="library-link">' in page
    assert 'id="home-radar-host"' in page
    assert "创建岗位雷达并开始扫描" in page
    assert 'aria-live="polite"' in page
    assert 'data-recommendation-scope="today"' in page
    assert "今日推荐" in page
    assert 'recommendationScope:"today"' in script
    assert 'params.set("scope","recommended")' not in script
    assert "选择使用方式" not in page


def test_web_ui_uses_one_reusable_radar_builder_and_no_social_recruitment(tmp_path: Path):
    client = TestClient(create_app(AppPaths(tmp_path / "profile")))
    page = client.get("/").text
    script = client.get("/static/js/app.js").text

    assert page.count('id="radar-builder-template"') == 1
    assert "job.first_seen||job.collected_date" not in script
    assert "formatDateTime(job.collected_date)" in script
    assert '"本次新增"' not in script
    assert 'id="onboarding-builder-host"' in page
    assert 'id="preferences-builder-host"' in page
    assert 'id="builder-radar-host"' in page
    assert 'id="home-radar-meta"' in page
    assert 'id="preferences-view"' not in page
    assert 'id="edit-preferences"' not in page
    assert 'class="radar-preview-column"' in page
    assert 'class="status-badge building"' in page
    assert "orbit-radar" in script
    assert "focusScore" in script
    assert "偏好聚焦度" in script
    assert "调整中" in script
    assert "监控中心" not in script
    assert "监控范围" not in script
    assert "非常宽泛" not in script
    assert "当前监控策略" not in page
    assert "radar-progress" not in page
    assert "radar-summary" not in page
    assert "保存并重新匹配岗位" in script
    assert "社会招聘" not in page
    assert "社会招聘" not in script
    assert 'scope:"all"' in script


def test_scan_status_restores_persisted_success_and_failure(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")
    repo = JobRepository(paths.database)
    repo.init_schema()
    assert TestClient(create_app(paths)).get("/api/scan/status").json()["state"] == "never"

    repo.record_scan_run({
        "run_type": "daily", "task_id": "success-1",
        "started_at": "2026-07-16T19:40:00", "finished_at": "2026-07-16T19:42:00",
        "status": "success", "pages_scanned": 2, "items_seen": 426,
        "new_items": 44, "updated_items": 3, "recommended_items": 12,
        "expiring_items": 5, "failure_stage": None, "error_message": None,
        "notification_status": "skipped",
    })
    client = TestClient(create_app(paths))
    restored = client.get("/api/scan/status").json()
    assert restored["state"] == "success"
    assert restored["last_success_at"] == "2026-07-16T19:42:00"
    assert restored["last_run"]["new_items"] == 44
    assert restored["last_run"]["recommended_items"] == 12

    repo.record_scan_run({
        "run_type": "daily", "task_id": "failed-1",
        "started_at": "2026-07-16T20:00:00", "finished_at": "2026-07-16T20:01:00",
        "status": "failed", "pages_scanned": 0, "items_seen": 0,
        "new_items": 0, "updated_items": 0, "recommended_items": 0,
        "expiring_items": 5, "failure_stage": "link_enrichment",
        "error_message": "redacted", "notification_status": "skipped",
    })
    restored = client.get("/api/scan/status").json()
    assert restored["state"] == "failed"
    assert restored["last_success_at"] == "2026-07-16T19:42:00"
    assert restored["last_run"]["failure_stage"] == "link_enrichment"


def test_recommended_jobs_support_scopes_filters_pagination_and_detail(tmp_path: Path):
    paths = AppPaths(tmp_path / "profile")
    repo = JobRepository(paths.database)
    repo.init_schema()
    now = datetime.now().replace(microsecond=0)
    first = repo.upsert_job(Job(
        dedupe_key="web:recommended-1", company="示例科技", title="算法工程师",
        summary="负责机器学习模型训练与部署", city="北京", batch="秋招",
        degree="硕士", target_graduate_year="2027届", company_type="民营企业",
        industry="人工智能", role_signals=["算法", "机器学习"],
        deadline=(now + timedelta(days=3)).date().isoformat(),
        collected_date=now.date().isoformat(),
        source_url="https://example.com/jobs/1", apply_url=None,
    ))
    second = repo.upsert_job(Job(
        dedupe_key="web:recommended-2", company="示例研究院", title="深度学习研究员",
        city="上海", batch="提前批", role_signals=["深度学习"],
        deadline=(now + timedelta(days=20)).date().isoformat(),
        collected_date=(now - timedelta(days=1)).date().isoformat(),
    ))
    old = repo.upsert_job(Job(
        dedupe_key="web:recommended-old", company="示例旧公司", title="旧岗位",
        collected_date=(now - timedelta(days=2)).date().isoformat(),
    ))
    repo.save_match(first.job_id, {"matched_keywords": ["算法"], "needs_verify": True})
    repo.append_recommendations(now.date().isoformat(), [
        {"job_id": first.job_id, "recommend_reason": "命中算法方向"},
        {"job_id": second.job_id, "recommend_reason": "命中深度学习方向"},
        {"job_id": old.job_id, "recommend_reason": "历史推荐"},
    ])
    repo.record_scan_run({
        "run_type": "daily", "task_id": "scan-1",
        "started_at": (now - timedelta(minutes=1)).isoformat(), "finished_at": now.isoformat(),
        "status": "success", "pages_scanned": 1, "items_seen": 2, "new_items": 2,
        "updated_items": 0, "recommended_items": 2, "expiring_items": 1,
        "failure_stage": None, "error_message": None, "notification_status": "skipped",
    })
    client = TestClient(create_app(paths))

    result = client.get(
        "/api/jobs?scope=today&direction=算法&city=北京&deadline_status=expiring&page=1&page_size=1"
    ).json()
    assert result["total"] == 1
    assert result["pages"] == 1
    assert result["items"][0]["title"] == "算法工程师"
    assert result["summary"]["today_recommended"] == 2
    assert result["summary"]["expiring"] == 1
    assert "民营企业" in result["facets"]["company_types"]

    detail = client.get(f"/api/jobs/{first.job_id}").json()
    assert detail["recommend_reason"] == "命中算法方向"
    assert detail["matched_keywords"] == "算法"
    assert detail["detail_url"] == "https://example.com/jobs/1"
    assert detail["apply_url"] is None
    assert client.get("/api/jobs/999999").status_code == 404


def test_preferences_returns_rematch_changes(tmp_path: Path, monkeypatch):
    from jobpicky.services.local import LocalRematchResult

    paths = AppPaths(tmp_path / "profile")
    repo = JobRepository(paths.database)
    repo.init_schema()
    repo.upsert_job(Job(dedupe_key="web:rematch", company="示例公司", title="FPGA 工程师"))
    monkeypatch.setattr(
        "jobpicky.services.local.rematch_local",
        lambda *_args, **_kwargs: (
            repo,
            LocalRematchResult(
                items_seen=1,
                new_items=0,
                updated_items=1,
                relevant_items=1,
                recommended_items=4,
                matched_items=1,
                added_recommended_items=2,
                removed_recommended_items=1,
            ),
        ),
    )
    client = TestClient(create_app(paths))

    result = client.put(
        "/api/preferences",
        json={"user_profile": {"batches": ["秋招"], "role_groups": ["硬件/嵌入式"]}},
    ).json()

    assert result["rematch"]["added_recommended_items"] == 2
    assert result["rematch"]["removed_recommended_items"] == 1
    assert result["rematch"]["recommended_items"] == 4


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
    assert preview["baseline_items"] == 802
    assert not paths.database.exists()
