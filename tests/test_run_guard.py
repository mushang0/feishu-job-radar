import os

import pytest

from job_monitor.run_guard import DailyRunGuard, DailyRunInProgress
from job_monitor.wondercv import WonderCVCrawler


def test_daily_run_guard_rejects_a_second_live_run(tmp_path):
    db_path = tmp_path / "jobs.sqlite"
    with DailyRunGuard(db_path):
        with pytest.raises(DailyRunInProgress):
            with DailyRunGuard(db_path):
                pass
    assert not db_path.with_suffix(".daily.lock").exists()


def test_daily_run_guard_recovers_a_stale_lock(tmp_path):
    db_path = tmp_path / "jobs.sqlite"
    lock_path = db_path.with_suffix(".daily.lock")
    lock_path.write_text('{"pid": 99999999}', encoding="utf-8")

    with DailyRunGuard(db_path):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_crawler_cancellation_stops_before_yielding_a_page():
    class Response:
        text = '<a href="/xiaozhao/acme"><h2>Acme 2027 FPGA engineer</h2></a>'

        def raise_for_status(self):
            return None

    cancelled = False

    def cancel_check():
        return cancelled

    def get(*_args, **_kwargs):
        nonlocal cancelled
        cancelled = True
        return Response()

    crawler = WonderCVCrawler(
        {"crawler": {"max_pages_daily": 1, "enrich_details": False}},
        get=get,
        sleep=lambda _: None,
        progress=lambda _: None,
        cancel_check=cancel_check,
    )

    result = crawler.crawl()

    assert result.interrupted is True
    assert result.jobs == []
