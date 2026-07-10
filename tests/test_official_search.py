from job_monitor.models import Job
from job_monitor.official_search import OfficialCandidate, OfficialUrlFinder, build_search_queries, parse_search_results, score_candidate


def test_score_candidate_prefers_official_recruiting_page_over_wondercv():
    job = Job(company="腾讯", title="混元青云计划 AI 全栈工程师", summary="校园招聘 投递")
    official = OfficialCandidate(
        url="https://join.qq.com/post.html?pid=ai",
        title="腾讯校园招聘 - 混元青云计划",
        snippet="AI全栈工程师 网申 投递 职位详情",
        source="search",
    )
    repost = OfficialCandidate(
        url="https://www.wondercv.com/xiaozhao/tencent-hunyuan/",
        title="腾讯混元青云计划招聘信息",
        snippet="校园招聘信息汇总",
        source="search",
    )

    assert score_candidate(job, official) > score_candidate(job, repost)


def test_score_candidate_prefers_recruiting_official_site_over_third_party_campus_page():
    job = Job(company="上海米哈游网络科技股份有限公司", title="上海米哈游网络科技股份有限公司")
    official = OfficialCandidate(
        url="https://jobs.mihoyo.com/",
        title="miHoYo社会招聘 - miHoYo招聘官网",
        snippet="",
        source="search",
    )
    third_party = OfficialCandidate(
        url="https://campus.niuqizp.com/job-vwy5zanaL.html",
        title="校招 米哈游 2027 校园招聘 技术提前批启动",
        snippet="第三方校园招聘信息",
        source="search",
    )

    assert score_candidate(job, official) > score_candidate(job, third_party)


def test_score_candidate_does_not_penalize_different_graduate_years():
    job = Job(company="大疆", title="2027届嵌入式工程师")
    candidate_2026 = OfficialCandidate(
        url="https://we.dji.com/campus/jobs/embedded",
        title="大疆 2026 校园招聘 嵌入式工程师",
        snippet="校园招聘 投递 职位详情",
        source="search",
    )
    candidate_2027 = OfficialCandidate(
        url="https://we.dji.com/campus/jobs/embedded-2027",
        title="大疆 2027 校园招聘 嵌入式工程师",
        snippet="校园招聘 投递 职位详情",
        source="search",
    )

    assert abs(score_candidate(job, candidate_2026) - score_candidate(job, candidate_2027)) <= 2


def test_finder_returns_highest_scoring_candidate():
    job = Job(company="欧莱雅", title="科技青年咖 AI 实习")
    candidates = [
        OfficialCandidate("https://example.com/news", "欧莱雅新闻", "品牌活动", "search"),
        OfficialCandidate("https://careers.loreal.com/campus/ai", "欧莱雅校园招聘", "AI 实习 投递", "search"),
    ]
    finder = OfficialUrlFinder(search=lambda query: candidates)

    assert finder.find_best(job) == "https://careers.loreal.com/campus/ai"


def test_finder_falls_back_to_search_url_when_no_candidates():
    job = Job(company="清华同衡", title="暑期实习")
    finder = OfficialUrlFinder(search=lambda query: [])

    assert finder.find_best(job).startswith("https://www.bing.com/search?")


def test_build_search_queries_adds_core_company_name_for_legal_entity():
    job = Job(company="腾讯科技（上海）有限公司", title="混元青云计划")

    queries = build_search_queries(job)

    assert queries[:3] == ["腾讯 校园招聘", "腾讯 招聘官网", "腾讯 招聘"]
    assert "腾讯 混元青云计划 校园招聘" in queries
    assert "腾讯科技（上海）有限公司 招聘" not in queries


def test_build_search_queries_removes_location_and_business_suffixes():
    job = Job(company="上海米哈游网络科技股份有限公司", title="上海米哈游网络科技股份有限公司")

    queries = build_search_queries(job)

    assert queries[:3] == ["米哈游 校园招聘", "米哈游 招聘官网", "米哈游 招聘"]
    assert all("上海米哈游网络" not in query for query in queries)


def test_finder_uses_search_url_when_all_candidates_are_low_quality():
    job = Job(company="上海米哈游网络科技股份有限公司", title="上海米哈游网络科技股份有限公司")
    candidates = [
        OfficialCandidate("https://ja.wikipedia.org/wiki/%E4%B8%8A%E6%B5%B7%E5%B8%82", "上海市 - Wikipedia", "", "search"),
        OfficialCandidate("https://kanji.jitenon.jp/kanji/163", "漢字 上海", "", "search"),
    ]
    finder = OfficialUrlFinder(search=lambda query: candidates)

    assert finder.find_best(job).startswith("https://www.bing.com/search?")


def test_finder_uses_search_url_when_candidate_lacks_company_signal():
    job = Job(company="国泰海通证券股份有限公司", title="国泰海通证券河南分公司暑期实习")
    candidates = [
        OfficialCandidate("https://www.cathaypacific.com/cx/sc_CN.html", "国泰航空官网", "招聘", "search")
    ]
    finder = OfficialUrlFinder(search=lambda query: candidates)

    assert finder.find_best(job).startswith("https://www.bing.com/search?")


def test_parse_search_results_decodes_bing_redirect_urls():
    html = """
    <li class="b_algo">
      <a href="https://v.qq.com/">qq.com</a>
      <h2>
        <a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9qb2luLnFxLmNvbS8">
          腾讯招聘
        </a>
      </h2>
    </li>
    """

    results = parse_search_results(html)

    assert results[0].url == "https://join.qq.com/"
    assert len(results) == 1
