import pytest

from jobpicky.models import Job
from jobpicky.wondercv import WonderCVCrawler, parse_wondercv_detail, parse_wondercv_list


def test_parse_wondercv_list_extracts_public_cards():
    html = """
    <html><body>
      <a class="job-card" href="/xiaozhao/abc123">
        <h2>示例公司 2027届 FPGA工程师校园招聘</h2>
        <span class="company">示例公司</span>
        <span class="city">上海</span>
        <span class="date">2026年6月15日</span>
        <span class="tag">硬件</span>
        <span class="tag">新能源</span>
      </a>
    </body></html>
    """

    jobs = parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {"示例公司": []})

    assert len(jobs) == 1
    assert jobs[0].source_job_id == "abc123"
    assert jobs[0].detail_url == "https://www.wondercv.com/xiaozhao/abc123"
    assert jobs[0].company == "示例公司"
    assert jobs[0].target_graduate_year == "2027届"
    assert jobs[0].collected_date == "2026-06-15"
    assert jobs[0].dedupe_key == "WonderCV:id:abc123"


def test_parse_wondercv_list_stops_on_login_or_captcha_page():
    html = "<html><body>请登录后继续访问 验证码</body></html>"

    try:
        parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {})
    except RuntimeError as exc:
        assert "公开页面受限" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_parse_wondercv_list_skips_xiaozhao_homepage_link():
    html = """
    <html><body>
      <a href="/xiaozhao/">校招信息</a>
      <a href="/xiaozhao/acme-11409-abc">
        <h2>示例公司 2027届 FPGA工程师校园招聘</h2>
        <span class="company">示例公司</span>
        <span class="date">收录 2026.07.02</span>
      </a>
    </body></html>
    """

    jobs = parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {})

    assert len(jobs) == 1
    assert jobs[0].detail_url == "https://www.wondercv.com/xiaozhao/acme-11409-abc"
    assert jobs[0].collected_date == "2026-07-02"


def test_parse_wondercv_detail_extracts_dji_role_keywords():
    html = """
    <html><body>
      <nav>简历模板 校招推荐 文章推荐</nav>
      <main>
        <h1>大疆27秋招</h1>
        <p>大疆创新2027届秋季校园招聘面向2027届毕业生。</p>
        <section>
          <h2>招聘岗位</h2>
          <p>图像算法工程师（深圳）：参与相机传感器设计。</p>
          <p>嵌入式工程师（上海）：基于芯片平台设计软件方案。</p>
          <p>GNSS定位算法工程师（北京）：负责定位算法研发。</p>
          <p>测试开发工程师：负责自动化测试平台。</p>
        </section>
        <a href="/jobs/dji/apply">立即投递</a>
      </main>
    </body></html>
    """

    detail = parse_wondercv_detail(html)

    assert "大疆创新2027届秋季校园招聘" in detail.raw_text
    assert detail.apply_url == "/jobs/dji/apply"
    assert {"图像算法", "嵌入式", "GNSS", "测试开发"}.issubset(set(detail.keywords))
    assert "简历模板" not in detail.summary
    assert [position.title for position in detail.positions] == [
        "图像算法工程师",
        "嵌入式工程师",
        "GNSS定位算法工程师",
        "测试开发工程师",
    ]
    assert [position.city for position in detail.positions[:3]] == ["深圳市", "上海市", "北京市"]


def test_parse_wondercv_detail_extracts_position_fields_without_mixing_roles():
    html = """
    <main>
      <h2>招聘岗位</h2>
      <h3>1. 嵌入式工程师（深圳）</h3>
      <p>岗位职责：负责 BSP 与驱动开发。</p>
      <p>任职要求：本科及以上；专业要求：电子信息、自动化；熟悉 RTOS。</p>
      <p>招聘人数：12人</p>
      <h3>2. 芯片验证工程师</h3>
      <p>岗位职责：搭建 UVM 验证环境。</p>
      <p>任职要求：硕士；熟悉 SystemVerilog。</p>
      <h2>招聘流程</h2>
      <p>统一笔试与面试。</p>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert len(detail.positions) == 2
    embedded, verification = detail.positions
    assert embedded.title == "嵌入式工程师"
    assert embedded.direction_id == "hardware.embedded"
    assert embedded.city == "深圳市"
    assert embedded.degree == "本科及以上"
    assert embedded.majors == ["电子信息", "自动化"]
    assert embedded.headcount == 12
    assert "BSP" in (embedded.responsibilities or "")
    assert "RTOS" in embedded.skills
    assert verification.title == "芯片验证工程师"
    assert verification.direction_id == "chip.verification"
    assert verification.city is None
    assert verification.location_status == "pending"
    assert {"UVM", "SystemVerilog"} <= set(verification.skills)
    assert "UVM" not in embedded.source_text
    assert "UVM" in (verification.source_text or "")


def test_direction_only_announcement_does_not_invent_position_records():
    html = """
    <main>
      <h2>招聘方向</h2>
      <p>技术类、产品类、运营类岗位将在官网陆续发布。</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert detail.positions == []


def test_parse_wondercv_detail_falls_back_to_recruiting_direction_keywords():
    html = """
    <html><body>
      <main>
        <h1>飞猪27秋招</h1>
        <p>飞猪2027届秋季校园招聘。</p>
        <h2>招聘方向</h2>
        <p>技术类 产品类 运营类</p>
        <h2>职位摘要</h2>
        <p>本次招聘覆盖数据、交互、平台研发等方向。</p>
      </main>
    </body></html>
    """

    detail = parse_wondercv_detail(html)

    assert {"技术", "产品", "运营", "数据", "研发"}.issubset(set(detail.keywords))
    assert "飞猪2027届秋季校园招聘" in detail.summary


def test_parse_wondercv_detail_ignores_recommended_job_tail():
    html = """
    <html><body>
      <nav>页面导航 招聘公告 校招推荐 文章推荐</nav>
      <main>
        <h1>普通岗位</h1>
        <h2>招聘公告与岗位信息</h2>
        <p>本岗位招聘客户经理助理。</p>
        <h2>投递建议</h2>
        <p>请按要求投递。</p>
        <h2>校招推荐</h2>
        <p>其他公司提供IP、SoC、ASIC三大芯片方向岗位。</p>
        <h2>文章推荐</h2>
        <p>更多内容。</p>
      </main>
    </body></html>
    """

    detail = parse_wondercv_detail(html)

    assert "客户经理助理" in detail.raw_text
    assert "ASIC" not in detail.raw_text
    assert "IC" not in detail.keywords


def test_parse_wondercv_detail_stops_role_text_before_workflow_and_advice():
    html = """
    <main>
      <h2>关联岗位</h2>
      <p>研究助理：负责行业数据整理与研究报告撰写。</p>
      <h2>招聘流程</h2>
      <p>面试名单按笔试成绩排序，HR负责候选人搜索。</p>
      <h2>投递建议</h2>
      <p>表现优秀者可获得职业推荐。</p>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert "研究助理" in detail.role_text
    assert "排序" not in detail.role_text
    assert "搜索" not in detail.role_text
    assert "推荐" not in detail.role_text


def test_parse_wondercv_detail_keeps_body_after_plain_text_navigation():
    html = """
    <html><body>
      页面导航 招聘公告 关联岗位 招聘流程 投递建议 FAQ 校招推荐 文章推荐
      首页 / 校招信息 / 深圳市大疆创新科技有限公司 / 大疆27秋招
      招聘公告与岗位信息
      招聘岗位
      嵌入式工程师：负责基于芯片平台设计软件方案。
      GNSS定位算法工程师：负责定位算法研发。
      校招推荐
      其他公司提供ASIC岗位。
    </body></html>
    """

    detail = parse_wondercv_detail(html)

    assert "嵌入式工程师" in detail.raw_text
    assert "GNSS定位算法工程师" in detail.raw_text
    assert "ASIC" not in detail.raw_text
    assert {"嵌入式", "GNSS"}.issubset(set(detail.keywords))


def test_parse_wondercv_detail_does_not_extract_ic_from_english_words():
    html = """
    <html><body>
      首页 / 校招信息 / 普通公司 / 普通岗位
      招聘公告与岗位信息
      岗位要求：熟练使用Office办公软件，具备Technical writing能力，
      可参与Human Computer Interaction资料整理。
    </body></html>
    """

    detail = parse_wondercv_detail(html)

    assert "IC" not in detail.keywords


def test_enrich_detail_failure_keeps_list_job():
    class Response:
        def raise_for_status(self):
            raise RuntimeError("network down")

    crawler = WonderCVCrawler({"crawler": {"enrich_details": True}}, get=lambda *args, **kwargs: Response(), sleep=lambda _: None)
    job = Job(
        detail_url="https://www.wondercv.com/xiaozhao/dji-11264/",
        company="深圳市大疆创新科技有限公司",
        title="大疆27秋招",
        raw_text="大疆27秋招 技术岗",
    )

    enriched = crawler.enrich_detail(job)

    assert enriched is job
    assert enriched.raw_text == "大疆27秋招 技术岗"
    assert enriched.parse_status == "detail_failed"
    assert "detail fetch failed" in (enriched.parse_note or "")


def test_detail_enrichment_overrides_card_fields_and_keeps_role_evidence():
    class Response:
        text = """
        <main>
          <h2>招聘岗位</h2>
          <p>嵌入式工程师（上海）：负责 BSP 和驱动开发。</p>
          <p>要求本科及以上，面向2027届，秋招。</p>
        </main>
        """

        def raise_for_status(self):
            return None

    crawler = WonderCVCrawler(
        {"crawler": {"enrich_details": True}, "system_taxonomy": {"company_aliases": {}}},
        get=lambda *args, **kwargs: Response(),
        sleep=lambda _: None,
    )
    job = Job(
        detail_url="https://www.wondercv.com/xiaozhao/acme-1/",
        company="示例公司",
        title="示例公司 2027 校招",
        city="北京",
        batch="春招",
        parse_status="list_only",
    )

    enriched = crawler.enrich_detail(job)

    assert enriched.parse_status == "detail_ready"
    assert enriched.city == "上海市"
    assert enriched.batch == "秋招"
    assert "嵌入式" in enriched.role_signals
    assert enriched.role_text and "BSP" in enriched.role_text
    assert '"city"' in (enriched.field_evidence or "")
    assert [position.title for position in enriched.positions] == ["嵌入式工程师"]
    assert enriched.positions[0].city == "上海市"
