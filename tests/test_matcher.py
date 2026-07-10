from job_monitor.matcher import Matcher
from job_monitor.models import Job


def _config() -> dict:
    return {
        "profile": {"version": 3},
        "user_profile": {
            "graduate_years": ["2027届"],
            "batches": ["秋招", "提前批", "实习"],
            "role_groups": ["硬件/嵌入式", "半导体/芯片", "开发/部署"],
            "target_industries": ["新能源", "半导体"],
            "target_cities": ["深圳", "上海"],
            "must_watch_companies": ["必看科技"],
            "exclude_role_groups": ["销售", "市场", "运营"],
            "recall_mode": "balanced",
            "daily_push_limit": 20,
        },
        "system_taxonomy": {
            "role_groups": {
                "硬件/嵌入式": ["硬件", "嵌入式", "单片机", "驱动开发", "FPGA"],
                "半导体/芯片": ["半导体", "芯片", "芯片验证"],
                "开发/部署": ["AI工程师", "AI算法", "AI Infra"],
            },
            "exclude_role_groups": {
                "销售": ["销售", "客户经理"],
                "市场": ["市场", "营销"],
                "运营": ["运营"],
            },
            "generic_role_terms": ["研发类", "技术类", "工程师类", "校招生", "管培生"],
            "important_company_types": ["上市公司", "央企", "国企", "外企"],
            "important_company_marks": ["知名大厂", "研究院"],
            "company_aliases": {"必看科技": ["必看集团"]},
        },
    }


def test_must_watch_company_pushes_generic_notice():
    matcher = Matcher(_config())
    job = Job(company="必看集团", title="必看集团2027届校园招聘正式启动", batch="秋招", target_graduate_year="2027届")

    result = matcher.match(job)

    assert result.should_push is True
    assert result.is_relevant is True
    assert result.recommend_reason == "命中必看公司"
    assert result.priority == "push"


def test_must_watch_company_cannot_bypass_an_explicit_excluded_role():
    matcher = Matcher(_config())
    job = Job(
        company="必看集团",
        title="2027届销售客户经理",
        batch="秋招",
        target_graduate_year="2027届",
    )

    result = matcher.match(job)

    assert result.should_push is False
    assert result.recommend_reason == ""


def test_role_group_hit_pushes_and_names_group():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届FPGA工程师", batch="秋招", target_graduate_year="2027届", city="深圳")

    result = matcher.match(job)

    assert result.should_push is True
    assert result.recommend_reason == "命中岗位方向：硬件/嵌入式"
    assert result.matched_keywords == ["FPGA"]


def test_target_industry_plus_generic_role_pushes():
    matcher = Matcher(_config())
    job = Job(
        company="新能源公司",
        title="2027届研发类校招生",
        batch="秋招",
        target_graduate_year="2027届",
        industry="新能源",
    )

    result = matcher.match(job)

    assert result.should_push is True
    assert result.recommend_reason == "目标行业下的研发/技术类岗位"


def test_important_company_fallback_does_not_create_a_pending_verification_recommendation():
    matcher = Matcher(_config())
    job = Job(
        company="重点公司",
        title="2027届校园招聘",
        batch="秋招",
        target_graduate_year="2027届",
        company_type="上市公司",
    )

    result = matcher.match(job)

    assert result.should_push is False
    assert result.needs_verify is False
    assert result.recommend_reason == ""


def test_city_only_does_not_push():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届", city="深圳")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.matched_city_rule == "深圳"


def test_industry_only_does_not_push():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届", industry="新能源")

    result = matcher.match(job)

    assert result.should_push is False


def test_graduate_year_mismatch_does_not_push():
    matcher = Matcher(_config())
    job = Job(company="必看科技", title="2026届校园招聘", batch="秋招", target_graduate_year="2026届")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.match_reason == "届别不匹配"


def test_batch_mismatch_does_not_push():
    matcher = Matcher(_config())
    job = Job(company="必看科技", title="2027届社招", batch="社招", target_graduate_year="2027届")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.match_reason == "批次不匹配"


def test_negative_only_does_not_push():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届销售管培生", batch="秋招", target_graduate_year="2027届")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.negative_keywords == ["销售"]
    assert result.match_reason == "命中排除岗位"


def test_negative_words_block_positive_role_group_signal():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届研发、销售、FPGA岗位", batch="秋招", target_graduate_year="2027届")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.negative_keywords == ["销售"]
    assert result.match_reason == "命中排除岗位"


def test_negative_words_in_raw_text_do_not_block_positive_role_group_signal():
    matcher = Matcher(_config())
    job = Job(
        company="普通公司",
        title="2027届FPGA工程师",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="本公告还开放销售管培生、市场营销实习生。",
    )

    result = matcher.match(job)

    assert result.should_push is True
    assert result.negative_keywords == ["销售", "市场", "营销"]
    assert result.recommend_reason == "命中岗位方向：硬件/嵌入式"


def test_must_watch_mixed_notice_with_an_explicit_excluded_role_is_not_recommended():
    matcher = Matcher(_config())
    job = Job(
        company="必看集团",
        title="必看集团2027届AI算法和营销岗位同步开放",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="岗位包括AI算法工程师、市场营销、运营。",
    )

    result = matcher.match(job)

    assert result.should_push is False
    assert result.needs_verify is False
    assert result.negative_keywords == ["营销"]
    assert result.recommend_reason == ""


def test_marketing_keyword_is_excluded_by_market_group():
    matcher = Matcher(_config())
    job = Job(company="普通公司", title="2027届在线营销FPGA实习生", batch="实习", target_graduate_year="2027届")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.negative_keywords == ["营销"]
    assert result.match_reason == "命中排除岗位"


def test_marketing_job_tag_blocks_positive_raw_text():
    matcher = Matcher(_config())
    job = Job(
        company="普通公司",
        title="2027届实习生",
        batch="实习",
        target_graduate_year="2027届",
        job_tags=["在线营销"],
        raw_text="技术团队还招聘FPGA工程师。",
    )

    result = matcher.match(job)

    assert result.should_push is False
    assert result.negative_keywords == ["营销"]
    assert result.match_reason == "命中排除岗位"


def test_ai_requires_qualified_role_term():
    matcher = Matcher(_config())
    phone_interview = Job(company="普通公司", title="2027届实习生", batch="实习", target_graduate_year="2027届", raw_text="投递后会有AI电话面试。")
    ai_role = Job(company="普通公司", title="2027届AI算法工程师", batch="实习", target_graduate_year="2027届")

    assert matcher.match(phone_interview).should_push is False
    assert matcher.match(ai_role).matched_keywords == ["AI算法"]


def test_negative_words_block_generic_industry_fallback_without_role_group_signal():
    matcher = Matcher(
        {
            "user_profile": {
                "graduate_years": ["2026"],
                "batches": ["fall"],
                "role_groups": ["algorithm"],
                "target_industries": ["internet"],
                "target_cities": [],
                "must_watch_companies": [],
                "exclude_role_groups": ["sales"],
            },
            "system_taxonomy": {
                "role_groups": {"algorithm": ["algorithm"]},
                "exclude_role_groups": {"sales": ["sales"]},
                "generic_role_terms": ["trainee"],
                "important_company_types": [],
                "important_company_marks": [],
                "company_aliases": {},
            },
        }
    )
    job = Job(company="OtherCo", title="2026 fall sales trainee", batch="fall", target_graduate_year="2026", industry="internet")

    result = matcher.match(job)

    assert result.should_push is False
    assert result.match_reason == "命中排除岗位"


def test_configured_city_filters_clear_mismatch_but_not_missing_city():
    matcher = Matcher(_config())
    mismatch = Job(company="必看科技", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届", city="广州")
    missing = Job(company="必看科技", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届")

    mismatch_result = matcher.match(mismatch)
    missing_result = matcher.match(missing)

    assert mismatch_result.should_push is False
    assert mismatch_result.match_reason == "城市不匹配"
    assert missing_result.should_push is True


def test_detail_keywords_in_raw_text_trigger_role_group_match():
    matcher = Matcher(
        {
            "profile": {"version": 4},
            "user_profile": {
                "graduate_years": ["2027届"],
                "batches": ["秋招"],
                "role_groups": ["硬件/嵌入式"],
                "target_industries": [],
                "target_cities": [],
                "must_watch_companies": [],
                "exclude_role_groups": ["销售"],
            },
            "system_taxonomy": {
                "role_groups": {"硬件/嵌入式": ["嵌入式", "GNSS", "测试开发"]},
                "exclude_role_groups": {"销售": ["销售"]},
                "generic_role_terms": [],
                "important_company_types": [],
                "important_company_marks": [],
                "company_aliases": {},
            },
        }
    )
    job = Job(
        company="深圳市大疆创新科技有限公司",
        title="大疆27秋招",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="招聘岗位：嵌入式工程师、GNSS定位算法工程师、测试开发工程师。",
    )

    result = matcher.match(job)

    assert result.should_push is True
    assert result.matched_keywords == ["嵌入式", "GNSS", "测试开发"]


def test_short_ascii_keyword_requires_token_boundary():
    matcher = Matcher(
        {
            "user_profile": {
                "graduate_years": ["2027届"],
                "batches": ["秋招"],
                "role_groups": ["半导体/芯片"],
                "target_industries": [],
                "target_cities": [],
                "must_watch_companies": [],
                "exclude_role_groups": [],
            },
            "system_taxonomy": {
                "role_groups": {"半导体/芯片": ["IC"]},
                "exclude_role_groups": {},
                "generic_role_terms": [],
                "important_company_types": [],
                "important_company_marks": [],
                "company_aliases": {},
            },
        }
    )
    false_positive = Job(
        company="普通公司",
        title="2027届秋招",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="public service policy practice logistics",
    )
    real_hit = Job(
        company="芯片公司",
        title="2027届秋招",
        batch="秋招",
        target_graduate_year="2027届",
        raw_text="招聘岗位：IC验证工程师。",
    )

    assert matcher.match(false_positive).should_push is False
    assert matcher.match(real_hit).matched_keywords == ["IC"]
