from job_monitor.alerts import build_daily_message


def test_build_daily_message_includes_recommended_jobs_and_reason():
    message = build_daily_message(
        total_new=2,
        relevant_rows=[
            {
                "company": "示例公司",
                "title": "FPGA工程师",
                "city": "上海",
                "recommend_reason": "命中岗位方向：硬件/嵌入式",
                "original_url": "https://example.com/job",
            }
        ],
    )

    assert "今日新增秋招信息：2 条" in message
    assert "推荐岗位：1 条" in message
    assert "示例公司 - FPGA工程师 - 上海" in message
    assert "https://example.com/job" in message
    assert "建议搜索" not in message
