from pathlib import Path

from job_monitor.exporters import build_feishu_record, export_jobs_to_excel
from job_monitor.matcher import Matcher
from job_monitor.models import Job
from job_monitor.storage import JobRepository
from job_monitor.wondercv import parse_wondercv_list


def _config():
    return {
        "profile": {"version": 7},
        "user_profile": {
            "graduate_years": ["2027届"],
            "batches": ["秋招"],
            "role_groups": ["硬件/嵌入式"],
            "target_industries": ["半导体"],
            "target_cities": ["Shanghai"],
            "must_watch_companies": ["TargetCo"],
            "exclude_role_groups": ["销售"],
            "recall_mode": "balanced",
            "daily_push_limit": 20,
        },
        "system_taxonomy": {
            "role_groups": {"硬件/嵌入式": ["FPGA", "embedded"]},
            "exclude_role_groups": {"销售": ["sales"]},
            "generic_role_terms": ["研发类", "engineer"],
            "important_company_types": ["上市公司"],
            "important_company_marks": ["研究院"],
            "company_aliases": {},
        },
    }


def test_parser_separates_clean_title_from_raw_text_and_tags():
    html = """
    <html><body>
      <a href="/xiaozhao/target-1">
        <h2>上市公司 电子 有内推 收录 2026.07.02 TargetCo TargetCo 2027 campus FPGA engineer Shanghai 秋招 本科 芯片</h2>
      </a>
    </body></html>
    """

    job = parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {})[0]

    assert job.raw_title.startswith("上市公司 电子 有内推 收录")
    assert job.title == "TargetCo 2027 campus FPGA engineer Shanghai"
    assert job.clean_title == job.title
    assert job.raw_text == job.raw_title
    assert job.company_type == "上市公司"
    assert job.industry == "电子"
    assert job.special_marks == ["有内推"]
    assert job.job_tags == ["芯片"]
    assert job.raw_tags
    assert job.parse_status == "ok"


def test_matcher_keeps_debug_fields_internal_while_deciding_push_binary():
    matcher = Matcher(_config())
    city_only = Job(company="OtherCo", title="2027届校园招聘", batch="秋招", target_graduate_year="2027届", city="Shanghai", industry="半导体")
    high = Job(company="RoleCo", title="2027届FPGA engineer", clean_title="2027届FPGA engineer", batch="秋招", target_graduate_year="2027届", city="Shanghai")

    city_result = matcher.match(city_only)
    high_result = matcher.match(high)

    assert city_result.priority == "skip"
    assert city_result.is_relevant is False
    assert city_result.should_push is False
    assert city_result.suggested_search_terms == []
    assert high_result.priority == "push"
    assert high_result.is_relevant is True
    assert high_result.should_push is True
    assert high_result.needs_verify is False
    assert high_result.matched_keywords == ["FPGA"]
    assert high_result.match_config_version == "7"


def test_storage_and_export_include_optimized_fields(tmp_path: Path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    job = Job(
        source="WonderCV",
        dedupe_key="WonderCV:id:1",
        company="TargetCo",
        company_normalized="TargetCo",
        raw_title="raw dirty title",
        title="TargetCo clean title",
        clean_title="TargetCo clean title",
        summary="short summary",
        raw_text="raw dirty title and details",
        batch="秋招",
        target_graduate_year="2027届",
        company_type="上市公司",
        industry="电子",
        job_tags=["芯片"],
        special_marks=["有内推"],
        raw_tags=["芯片", "有内推"],
        parse_status="ok",
    )
    inserted = repo.upsert_job(job)
    repo.save_match(inserted.job_id, Matcher(_config()).match(job))

    row = repo.get_job_with_match(inserted.job_id)
    record = build_feishu_record(row)
    output = export_jobs_to_excel([row], tmp_path / "jobs.xlsx")

    assert row["raw_title"] == "raw dirty title"
    assert row["clean_title"] == "TargetCo clean title"
    assert "公司" in record["fields"]
    assert "原始抓取标题" not in record["fields"]
    assert "是否推送" not in record["fields"]
    assert "匹配分数" not in record["fields"]
    assert output.exists()
