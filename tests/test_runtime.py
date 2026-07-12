from job_monitor.runtime import RunEvent, RunReport, RunReporter


def test_run_report_explains_no_new_recommendations():
    report = RunReport(
        "daily", "success", items_seen=36, new_items=26, recommended_items=0,
        current_workspace_items=42, advice="本次没有新的匹配岗位，飞书无需更新。",
    )

    text = report.render()

    assert "今日扫描完成" in text
    assert "抓取岗位：36 条" in text
    assert "新推荐：0 条" in text
    assert "当前工作台岗位：42 条" in text
    assert "飞书无需更新" in text


def test_run_reporter_forwards_stage_and_report():
    events = []
    reports = []
    reporter = RunReporter(events.append, reports.append)

    reporter.stage("daily", 1, 5, "扫描", "done", "抓取 1 条")
    report = RunReport("daily", "success")
    reporter.finish(report)

    assert events == [RunEvent("daily", 1, 5, "扫描", "done", "抓取 1 条")]
    assert reports == [report]
