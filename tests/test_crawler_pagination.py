from jobpicky.wondercv import WonderCVCrawler, _print_progress


def test_wondercv_crawler_fetches_multiple_pages_when_configured():
    calls = []

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    def fake_get(url, timeout, headers):
        calls.append(url)
        suffix = "one" if len(calls) == 1 else "two"
        return Response(
            f"""
            <html><body>
              <a href="/xiaozhao/acme-{suffix}">
                <h2>Acme {suffix} 2027 campus FPGA engineer</h2>
                <span class="company">Acme</span>
                <span class="date">2026.07.02</span>
              </a>
            </body></html>
            """
        )

    crawler = WonderCVCrawler(
        {"crawler": {"max_pages_init": 2, "enrich_details": False, "min_interval_seconds": 0, "max_interval_seconds": 0}},
        get=fake_get,
        sleep=lambda _: None,
    )

    result = crawler.crawl(mode="init")

    assert [job.source_job_id for job in result.jobs] == ["acme-one", "acme-two"]
    assert calls == ["https://www.wondercv.com/xiaozhao/", "https://www.wondercv.com/xiaozhao/page/pn2/"]


def test_wondercv_crawler_marks_partial_when_a_later_page_fails():
    calls = []

    class Response:
        text = """
        <a href="/xiaozhao/acme-one"><h2>Acme 2027 FPGA engineer</h2><span class="company">Acme</span></a>
        """

        def raise_for_status(self):
            return None

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("network down")
        return Response()

    crawler = WonderCVCrawler(
        {"crawler": {"max_pages_daily": 2, "enrich_details": False, "min_interval_seconds": 0, "max_interval_seconds": 0}},
        get=fake_get,
        sleep=lambda _: None,
    )

    result = crawler.crawl()

    assert len(result.jobs) == 1
    assert result.partial is True
    assert "第 2 页" in str(result.error)


def test_wondercv_crawler_stops_before_detail_backfill_for_known_page():
    calls = []

    class Response:
        text = """
        <a href=\"/xiaozhao/acme-known\"><h2>Acme 2027 FPGA engineer</h2><span class=\"company\">Acme</span></a>
        """

        def raise_for_status(self):
            return None

    def fake_get(url, timeout, headers):
        calls.append(url)
        return Response()

    messages = []
    crawler = WonderCVCrawler(
        {"crawler": {"max_pages_daily": 2, "enrich_details": True}},
        get=fake_get,
        sleep=lambda _: None,
        progress=messages.append,
    )

    result = crawler.crawl(should_stop=lambda _: True)

    assert result.jobs == []
    assert result.pages_scanned == 0
    assert calls == ["https://www.wondercv.com/xiaozhao/"]
    assert messages[-1] == "第 1 页均为已处理岗位，日常扫描完成。"


def test_wondercv_crawler_reports_detail_progress_for_each_job():
    calls = []

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    def fake_get(url, timeout, headers):
        calls.append(url)
        if len(calls) == 1:
            return Response("""
            <a href=\"/xiaozhao/acme-new\"><h2>Acme 2027 FPGA engineer</h2><span class=\"company\">Acme</span></a>
            """)
        return Response("<main>招聘岗位 FPGA</main>")

    messages = []
    crawler = WonderCVCrawler(
        {"crawler": {"max_pages_daily": 1, "enrich_details": True, "min_interval_seconds": 0, "max_interval_seconds": 0}},
        get=fake_get,
        sleep=lambda _: None,
        progress=messages.append,
    )

    result = crawler.crawl(should_stop=lambda _: False)

    assert len(result.jobs) == 1
    assert any("详情回填：第 1 页 1/1 - Acme" in message for message in messages)
    assert messages[-1] == "详情回填：第 1 页 1/1 - 完成"


def test_progress_output_is_flushed(monkeypatch):
    captured = {}

    def fake_print(message, *, flush):
        captured["message"] = message
        captured["flush"] = flush

    monkeypatch.setattr("builtins.print", fake_print)

    _print_progress("正在抓取")

    assert captured == {"message": "正在抓取", "flush": True}
