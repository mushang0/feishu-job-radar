import pytest

from jobpicky.models import Job
from jobpicky.wondercv import (
    DetailParseResult,
    WonderCVCrawler,
    extract_wondercv_card_summary,
    merge_detail_into_job,
    parse_wondercv_detail,
    parse_wondercv_list,
)


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


def test_parse_wondercv_list_reads_current_card_date_and_text_fallback():
    html = """
    <a href="/xiaozhao/current-date-1">
      <span class="card-date">收录 2026.07.15</span><div class="company">甲公司</div>
    </a>
    <a href="/xiaozhao/current-date-2">
      <span class="site-renamed-date">收录 2026.07.14</span><div class="company">乙公司</div>
    </a>
    """

    jobs = parse_wondercv_list(html, "https://www.wondercv.com/xiaozhao/", {})

    assert [job.collected_date for job in jobs] == ["2026-07-15", "2026-07-14"]


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


def test_realistic_summary_and_table_positions_are_deduplicated_without_duty_sentences():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <p>算法工程师：负责工业控制算法研发与优化，工作地点深圳、上海。</p>
      <p>软件工程师：负责嵌入式系统开发与调试，工作地点深圳、苏州。</p>
      <p>硬件工程师：参与工业控制器硬件设计与测试。</p>
      <p>结构工程师：负责产品结构设计。</p>
      <p>岗位</p><p>专业要求</p><p>技能要求</p>
      <p>算法工程师</p><p>计算机、自动化、数学</p><p>C/C++/Python</p>
      <p>软件工程师</p><p>计算机、软件工程</p><p>C语言、RTOS</p>
      <p>硬件工程师</p><p>电子、电气、自动化</p><p>PCB布局</p>
      <p>结构工程师</p><p>机械、材料</p><p>SolidWorks</p>
      <p>负责工业控制算法研发与优化</p>
      <p>参与工业控制器硬件设计与测试</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == [
        "算法工程师", "软件工程师", "硬件工程师", "结构工程师",
    ]
    assert all(not position.title.startswith(("负责", "参与")) for position in detail.positions)


def test_realistic_category_and_bilingual_lists_split_into_positions():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <p>技术研发类：AI大模型工程师、产品研发工程师、海外财务</p>
      <p>北京：Wireless Researcher（无线通信研究员）、Edge-Cloud AI Intern（边缘-云人工智能实习生）</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == [
        "AI大模型工程师", "产品研发工程师", "海外财务", "无线通信研究员", "边缘-云人工智能实习生",
    ]
    assert [position.city for position in detail.positions[-2:]] == ["北京市", "北京市"]


def test_generated_position_summaries_keep_title_and_reject_duty_as_title():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <p>教师培训生，涵盖高中班级教师和少儿素养教师，工作地点大连。</p>
      <p>新媒体实习生，负责社群私域、直播与短视频运营，工作地点合肥。</p>
      <p>高中化学教师，负责授课、教研和学情反馈，工作地点合肥。</p>
      <p>新媒体运营，负责平台投放和数据复盘，工作地点合肥。</p>
      <p>考研学习顾问，负责学业规划咨询和学员服务，工作地点武汉。</p>
      <p>负责平台投放和数据复盘</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == [
        "教师培训生", "新媒体实习生", "高中化学教师", "新媒体运营", "考研学习顾问",
    ]


def test_related_position_title_survives_when_site_wraps_it_in_unparsed_divs():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <div>关联岗位 <span>投资银行部暑期实习生</span> 有机会了解投行项目运作全流程。</div>
      <p>项目简介</p>
      <p>项目面向2027届毕业生。</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == ["投资银行部暑期实习生"]


def test_explicit_flat_position_list_is_recovered_from_detail_text():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <div>本次招聘岗位为教学科研人员和辅导员。具体要求请查阅岗位表。</div>
      <p>岗位要求需查看附件。</p>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == ["教学科研人员", "辅导员"]


def test_authoritative_role_cards_recover_titles_outside_the_suffix_whitelist():
    html = """
    <main>
      <h2>关联岗位</h2>
      <section id="jobs">
        <div class="role-item"><strong>会计岗</strong><p>要求本科及以上，负责财务核算。</p></div>
        <div class="role-item"><strong>AI算法工程师-大模型</strong><p>要求硕士及以上，负责模型研发。</p></div>
        <div class="role-item"><strong>预培生</strong><p>参与研发设计核心工作。</p></div>
      </section>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == ["会计岗", "AI算法工程师-大模型", "预培生"]
    assert detail.degree == "本科及以上"
    assert all(position.confidence == 0.99 for position in detail.positions)


def test_role_cards_and_position_table_merge_codes_without_duplicates():
    html = """
    <main>
      <h2>招聘公告与岗位信息</h2>
      <table>
        <tr><th>岗位编号</th><th>岗位名称</th><th>工作地点</th></tr>
        <tr><td>Int03</td><td>医学信号处理算法研究工程师</td><td>深圳、武汉</td></tr>
        <tr><td>Int04</td><td>医学图像处理研究工程师</td><td>深圳</td></tr>
      </table>
      <section id="jobs">
        <h2>关联岗位</h2>
        <div class="role-item"><strong>Int03 医学信号处理算法研究工程师</strong><p>负责医疗设备核心信号处理算法。</p></div>
      </section>
      <h2>招聘流程</h2>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == [
        "医学信号处理算法研究工程师", "医学图像处理研究工程师",
    ]


def test_position_table_uses_the_job_column_not_requirements_or_majors():
    html = """
    <main>
      <table>
        <tr><th>招聘类别</th><th>招聘人数</th><th>招聘对象</th></tr>
        <tr><td>总部管培生</td><td>4人</td><td>全日制硕士及以上学历的2026届毕业生</td></tr>
        <tr><td>所属企业校招岗位</td><td>62人</td><td>全日制大专及以上学历的2026届毕业生</td></tr>
      </table>
      <table>
        <tr><th>招聘部门</th><th>人数</th><th>专业要求</th></tr>
        <tr><td>规划分院</td><td>5人</td><td>城乡规划 / 建筑学 / 风景园林</td></tr>
      </table>
      <table>
        <tr><th>岗位方向</th><th>专业要求</th></tr>
        <tr><td>燃气运营类</td><td>燃气工程、自动化</td></tr>
      </table>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == ["总部管培生", "燃气运营类"]


def test_role_cards_reject_a_cross_company_announcement_mix():
    html = """
    <main>
      <h1>海天味业27届实习</h1>
      <section id="jobs">
        <div class="role-item"><strong>警务辅助人员</strong><p>武汉市公安局黄陂区分局公开招聘警务辅助人员。</p></div>
        <div class="role-item"><strong>博士后</strong><p>山东第一医科大学面向海内外公开招聘博士后研究人员。</p></div>
        <div class="role-item"><strong>某学院招聘公告</strong><p>某学院招聘公告。</p></div>
      </section>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert detail.positions == []


def test_campaign_role_cards_require_evidence_in_the_announcement():
    html = """
    <main>
      <h1>中国核电27届秋招</h1>
      <p>中国核电2026校园招聘项目，具体岗位未在公告中列出。</p>
      <section id="jobs">
        <div class="role-item"><strong>中国核电2026校园招聘</strong><p>中国核电2026校园招聘项目。</p></div>
        <div class="role-item"><strong>编导助理</strong><p>工作地点杭州。</p></div>
        <div class="role-item"><strong>保险康养顾问</strong><p>工作地点绥化。</p></div>
      </section>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert detail.positions == []


def test_position_titles_remove_batch_codes_salary_and_location():
    html = """
    <main>
      <h2>岗位包括数字设计工程师、AI Agent工程师、理科老师、软件开发类、IC封装工程师、JAVA开发工程师、算法研发岗、启明星实习生、车辆调度研发工程师和考研学习顾问</h2>
      <section id="jobs">
        <div class="role-item"><strong>【校招】数字设计工程师(007998)</strong><p>工作地点深圳。</p></div>
        <div class="role-item"><strong>AI Agent工程师-北京</strong><p>负责智能体研发。</p></div>
        <div class="role-item"><strong>年薪15-25万理科老师</strong><p>负责课程教学。</p></div>
        <div class="role-item"><strong>软件开发类-27届提前批</strong><p>负责软件开发。</p></div>
        <div class="role-item"><strong>（26届）JW26001-IC封装工程师（热设计/3DIC/封装SI/系统级晶圆/光电合封/封装设计/封装工艺/封装应力）</strong><p>负责封装研发。</p></div>
        <div class="role-item"><strong>应届本科毕业生</strong><p>专业包括电气、自动化和计算机。</p></div>
        <div class="role-item"><strong>具有工作经验的专业人才</strong><p>需持有注册工程师证书。</p></div>
        <div class="role-item"><strong>JAVA开发工程师（2027届校园招聘）</strong><p>负责服务端研发。</p></div>
        <div class="role-item"><strong>精英计划-算法研发岗</strong><p>负责算法研发。</p></div>
        <div class="role-item"><strong>🔹 启明星实习生</strong><p>参与教学支持。</p></div>
        <div class="role-item"><strong>阿里星顶尖人才计划</strong><p>面向顶尖青年人才。</p></div>
        <div class="role-item"><strong>某公司2027届暑期实习招聘</strong><p>具体岗位待公布。</p></div>
        <div class="role-item"><strong>2026年第一次公开招聘入口</strong><p>点击入口查看岗位。</p></div>
        <div class="role-item"><strong>【2026届春招】车辆调度研发工程师</strong><p>负责调度研发。</p></div>
        <div class="role-item"><strong>武汉-考研学习顾问-26校招</strong><p>负责学习规划。</p></div>
        <div class="role-item"><strong>精英计划补招岗（仅限26届）</strong><p>具体岗位待确认。</p></div>
        <div class="role-item"><strong>硕士推免生预选拔</strong><p>面向优秀本科毕业生。</p></div>
      </section>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == [
        "数字设计工程师", "AI Agent工程师", "理科老师", "软件开发类", "IC封装工程师",
        "JAVA开发工程师", "算法研发岗", "启明星实习生", "车辆调度研发工程师", "考研学习顾问",
    ]


def test_department_role_cards_expand_explicit_intern_directions():
    html = """
    <main>
      <section id="jobs">
        <div class="role-item">
          <strong>技术创新中心（2026年实习）(J10933)</strong>
          <p>招聘研究助理、产品经理助理、数据分析等方向实习生，要求本科及以上。</p>
        </div>
      </section>
    </main>
    """

    detail = parse_wondercv_detail(html)

    assert [position.title for position in detail.positions] == ["研究助理", "产品经理助理", "数据分析"]


def test_detail_merge_keeps_wondercv_list_card_summary():
    job = Job(summary="面向2027届毕业生，开放12个研发岗位。")
    detail = DetailParseResult(raw_text="详情正文", summary="详情正文很长，不能覆盖列表卡片摘要。")

    merge_detail_into_job(job, detail)

    assert job.summary == "面向2027届毕业生，开放12个研发岗位。"


def test_card_summary_can_be_recovered_from_stored_discovery_text():
    raw_title = "上市公司 医疗 收录 2026.06.09 迈瑞医疗 迈瑞医疗2027届暑期实习生招聘，面向全球2027届毕业生，提供12个岗位。 深圳市 本科"

    summary = extract_wondercv_card_summary(raw_title)

    assert summary.startswith("迈瑞医疗2027届暑期实习生招聘")
    assert "提供12个岗位" in summary


def test_card_summary_stops_at_a_complete_sentence_instead_of_cropping_detail_text():
    raw_title = (
        "央企 科技 收录 2026.07.10 示例集团 "
        "示例集团2027届校园招聘全面启动。面向2027届毕业生开放技术研发与经营管理岗位。"
        "公司历史、福利制度、招聘流程、全国业务布局、培养体系、薪酬结构、办公环境和企业文化等大段详情不应继续塞进列表卡片。 北京市 本科"
    )

    summary = extract_wondercv_card_summary(raw_title)

    assert summary == "示例集团2027届校园招聘全面启动。面向2027届毕业生开放技术研发与经营管理岗位。"
    assert len(summary) <= 120


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
