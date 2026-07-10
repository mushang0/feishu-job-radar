from job_monitor.wondercv import WonderCVCrawler


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
