from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from ..official_search import OfficialUrlFinder
from ..pipeline import pull_user_states_from_feishu, run_daily_with_jobs
from ..run_guard import DailyRunGuard
from ..runtime import RunReport, RunReporter
from ..seed import restore_seed_database
from ..storage import JobRepository
from ..wondercv import EXTRACTION_VERSION, WonderCVCrawler
from .synchronization import SyncSummary, sync_feishu


@dataclass(frozen=True, slots=True)
class DailyWorkflowResult:
    status: str
    task_id: str
    items_seen: int = 0
    new_items: int = 0
    recommended_items: int = 0
    feishu_created: int = 0
    feishu_updated: int = 0
    feishu_failed: int = 0
    error: str = ""


def run_daily_workflow(
    config: dict,
    db_path: str | Path,
    *,
    reporter: RunReporter | None = None,
    cancel_check: Callable[[], bool] | None = None,
    skip_feishu: bool = False,
    task_id: str | None = None,
) -> DailyWorkflowResult:
    """Run one daily scan for non-CLI callers such as the WebUI.

    The workflow deliberately returns data instead of printing.  The legacy
    CLI keeps its richer text report for now and will migrate to this service
    in a later cutover phase.
    """
    reporter = reporter or RunReporter()
    cancel_check = cancel_check or (lambda: False)
    task_id = task_id or uuid4().hex
    repo = JobRepository(db_path)
    repo.init_schema()
    started_at = datetime.now().isoformat(timespec="seconds")

    try:
        with DailyRunGuard(db_path) as guard:
            def is_cancelled() -> bool:
                return cancel_check() or guard.cancelled.is_set()

            crawler = WonderCVCrawler(config, cancel_check=is_cancelled)
            last_run_date = repo.get_last_successful_run_date("daily")

            def should_stop(page_jobs) -> bool:
                if not page_jobs:
                    return True
                if all(
                    repo.job_exists(job.dedupe_key)
                    and not repo.job_requires_detail_enrichment(job.dedupe_key, EXTRACTION_VERSION)
                    for job in page_jobs
                ):
                    return True
                return bool(
                    last_run_date
                    and all(not job.collected_date or job.collected_date < last_run_date for job in page_jobs)
                )

            reporter.stage("daily", 1, 4, "扫描 WonderCV 新岗位")
            crawl = crawler.crawl(mode="daily", should_stop=should_stop)
            reporter.stage("daily", 1, 4, "扫描 WonderCV 新岗位", "done", f"抓取 {len(crawl.jobs)} 条")
            if crawl.interrupted or is_cancelled():
                return _finish(repo, started_at, task_id, "interrupted", crawl=crawl, error=crawl.error or "任务已取消")

            reporter.stage("daily", 2, 4, "匹配岗位偏好")
            summary = run_daily_with_jobs(repo, crawl.jobs, config)
            reporter.stage("daily", 2, 4, "匹配岗位偏好", "done", f"新推荐 {summary.recommended_items} 条")

            sync_summary = SyncSummary()
            if not skip_feishu and _feishu_is_configured(config):
                reporter.stage("daily", 3, 4, "补全官方投递链接")
                enrich = _enrich_official_urls(repo)
                reporter.stage("daily", 3, 4, "补全官方投递链接", "done", f"更新 {enrich} 条")
                if not is_cancelled():
                    reporter.stage("daily", 4, 4, "同步到飞书")
                    sync_summary = sync_feishu(repo, config, repo.list_feishu_sync_candidates())
                    reporter.stage("daily", 4, 4, "同步到飞书", "done", f"新建 {sync_summary.created} 条")

            status = "partial" if crawl.error or sync_summary.failed else "success"
            return _finish(
                repo,
                started_at,
                task_id,
                status,
                crawl=crawl,
                summary=summary,
                sync_summary=sync_summary,
                error=crawl.error or (f"飞书同步失败 {sync_summary.failed} 条" if sync_summary.failed else ""),
            )
    except Exception as exc:
        logging.exception("daily web workflow failed")
        repo.record_scan_run({
            "run_type": "daily",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "partial",
            "pages_scanned": 0,
            "items_seen": 0,
            "new_items": 0,
            "updated_items": 0,
            "error_message": str(exc),
        })
        return DailyWorkflowResult(status="failed", task_id=task_id, error=str(exc))


def _finish(repo, started_at, task_id, status, *, crawl, summary=None, sync_summary=None, error=""):
    summary = summary or type("Summary", (), {"items_seen": 0, "new_items": 0, "updated_items": 0, "recommended_items": 0})()
    sync_summary = sync_summary or SyncSummary()
    repo.record_scan_run({
        "run_type": "daily",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "pages_scanned": crawl.pages_scanned,
        "items_seen": summary.items_seen,
        "new_items": summary.new_items,
        "updated_items": summary.updated_items,
        "error_message": error or None,
    })
    return DailyWorkflowResult(
        status=status,
        task_id=task_id,
        items_seen=summary.items_seen,
        new_items=summary.new_items,
        recommended_items=summary.recommended_items,
        feishu_created=sync_summary.created,
        feishu_updated=sync_summary.updated,
        feishu_failed=sync_summary.failed,
        error=error,
    )


def _enrich_official_urls(repo: JobRepository) -> int:
    finder = OfficialUrlFinder()
    updated = 0
    for row in repo.list_recommended_jobs():
        if row.get("official_url"):
            continue
        from ..pipeline import _job_from_row

        url = finder.find_best(_job_from_row(row))
        job_id = int(row["job_id"])
        if url and repo.update_official_url_if_empty(job_id, url):
            updated += 1
    return updated


def _feishu_is_configured(config: dict) -> bool:
    feishu = config.get("feishu", {})
    return bool(
        (feishu.get("bitable_app_token") or feishu.get("base_url"))
        and (feishu.get("workspace_table_id") or feishu.get("table_id"))
        and (feishu.get("tenant_access_token") or (feishu.get("app_id") and feishu.get("app_secret")))
    )
