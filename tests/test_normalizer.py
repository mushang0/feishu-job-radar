from job_monitor.normalizer import (
    build_dedupe_key,
    normalize_company,
    normalize_date,
)


def test_build_dedupe_key_prefers_source_job_id():
    key = build_dedupe_key(
        source="WonderCV",
        source_job_id="abc123",
        detail_url="https://www.wondercv.com/jobs/999",
        company_normalized="Acme",
        title="2027 校园招聘",
        batch="秋招",
        collected_date="2026-06-15",
    )

    assert key == "WonderCV:id:abc123"


def test_build_dedupe_key_falls_back_to_normalized_detail_url():
    key = build_dedupe_key(
        source="WonderCV",
        source_job_id="",
        detail_url="https://www.wondercv.com/jobs/999?from=list#top",
        company_normalized="Acme",
        title="2027 校园招聘",
        batch="秋招",
        collected_date="2026-06-15",
    )

    assert key == "WonderCV:url:https://www.wondercv.com/jobs/999"


def test_build_dedupe_key_uses_company_title_batch_date_as_last_resort():
    key = build_dedupe_key(
        source="WonderCV",
        source_job_id=None,
        detail_url=None,
        company_normalized="Acme",
        title="2027 校园招聘",
        batch="提前批",
        collected_date="2026-06-15",
    )

    assert key == "WonderCV:combo:Acme|2027 校园招聘|提前批|2026-06-15"


def test_normalize_date_supports_iso_and_chinese_dates():
    assert normalize_date("2026-06-15") == "2026-06-15"
    assert normalize_date("2026.07.02") == "2026-07-02"
    assert normalize_date("2026年6月5日") == "2026-06-05"
    assert normalize_date("") is None


def test_normalize_company_applies_alias_mapping():
    aliases = {"示例公司A": ["示例A集团", "示例A科技"]}

    assert normalize_company("示例A集团 2027校园招聘", aliases) == "示例公司A"
