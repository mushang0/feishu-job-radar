from __future__ import annotations

from dataclasses import dataclass
import base64
import html
from html.parser import HTMLParser
import math
import re
from typing import Callable
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

import requests

from .models import Job


@dataclass(frozen=True, slots=True)
class OfficialCandidate:
    url: str
    title: str = ""
    snippet: str = ""
    source: str = "search"


SearchFn = Callable[[str], list[OfficialCandidate]]


class OfficialUrlFinder:
    def __init__(
        self,
        search: SearchFn | None = None,
        get: Callable[..., requests.Response] | None = None,
        search_url_template: str = "https://www.bing.com/search?setlang=zh-CN&mkt=zh-CN&cc=CN&q={query}",
        min_candidate_score: float = 25,
    ):
        self.get = get or requests.get
        self.search_url_template = search_url_template
        self.min_candidate_score = min_candidate_score
        self.search = search or self._search_web

    def find_best(self, job: Job) -> str:
        queries = build_search_queries(job)
        best: OfficialCandidate | None = None
        best_score = -math.inf
        for query in queries:
            try:
                candidates = self.search(query)
            except Exception:
                candidates = []
            for candidate in candidates:
                if not has_company_signal(job, candidate):
                    continue
                score = score_candidate(job, candidate)
                if score > best_score:
                    best = candidate
                    best_score = score
        if best and best_score >= self.min_candidate_score:
            return best.url
        return self._search_url(queries[0] if queries else job.company or job.title)

    def _search_web(self, query: str) -> list[OfficialCandidate]:
        response = self.get(self._search_url(query), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return parse_search_results(response.text)

    def _search_url(self, query: str) -> str:
        return self.search_url_template.format(query=quote_plus(query))


def build_search_queries(job: Job) -> list[str]:
    company = _clean(job.company_normalized or job.company)
    core_company = _core_company_name(company)
    title = _clean(job.clean_title or job.title)
    queries: list[str] = []
    search_company = core_company or company
    if search_company:
        queries.append(f"{search_company} 校园招聘")
        queries.append(f"{search_company} 招聘官网")
        queries.append(f"{search_company} 招聘")
    if search_company and title and title != company:
        queries.append(f"{search_company} {title} 校园招聘")
        queries.append(f"{search_company} {title} 招聘")
    elif title and not search_company:
        queries.append(f"{title} 校园招聘")
    return list(dict.fromkeys(queries)) or ["招聘"]


def score_candidate(job: Job, candidate: OfficialCandidate) -> float:
    url = candidate.url.lower()
    parsed = urlparse(candidate.url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    text = _clean(" ".join([candidate.title, candidate.snippet, candidate.url]))
    company_terms = _company_terms(job)
    title_terms = _tokens(" ".join([job.clean_title or job.title, job.summary or "", " ".join(job.job_tags)]))

    score = 0.0
    if _contains_any(host + path, ["career", "careers", "campus", "jobs", "join", "zhaopin", "recruit"]):
        score += 35
    if _contains_any(host, ["career", "careers", "jobs", "join"]):
        score += 10
    if "mp.weixin.qq.com" in host:
        score += 12
    if _contains_any(url, ["wondercv.com", "jianli", "resume"]):
        score -= 25
    if _contains_any(
        host,
        [
            "niuqizp.com",
            "zhipin.com",
            "zhihu.com",
            "yingjiesheng.com",
            "upcv.tech",
            "51job.com",
            "zhaopin.com",
            "liepin.com",
            "kanzhun.com",
            "book118.com",
            "doc88.com",
            "max.book118.com",
        ],
    ):
        score -= 30
    if _contains_any(host, ["wikipedia.org", "kanji.", "jitenon.jp", "trip.com", "qpon.fun", "mamanoko.jp"]):
        score -= 30
    if _contains_any(text, ["简历模板", "培训", "课程"]):
        score -= 20
    if _contains_any(text, ["汇总", "合集"]):
        score -= 6

    for term in company_terms:
        if term and term.lower() in text.lower():
            score += 30
            break
    for term in company_terms:
        if term and term.lower() in host:
            score += 35
            break
    if _contains_any(text, ["招聘", "校招", "校园招聘", "实习", "投递", "网申", "职位", "岗位"]):
        score += 25
    if _contains_any(text, ["招聘官网", "官方招聘", "官网"]):
        score += 30
    if _contains_any(text, ["投递", "网申", "申请", "apply"]):
        score += 10

    score += _token_overlap_score(title_terms, _tokens(text), max_points=25)
    return score


def has_company_signal(job: Job, candidate: OfficialCandidate) -> bool:
    text = _clean(" ".join([candidate.title, candidate.snippet, candidate.url])).lower()
    return any(term and term.lower() in text for term in _company_terms(job))


def parse_search_results(html: str) -> list[OfficialCandidate]:
    parser = _SearchResultParser()
    parser.feed(html)
    return parser.results


def _token_overlap_score(needles: list[str], haystack: list[str], max_points: int) -> float:
    if not needles or not haystack:
        return 0.0
    hay = set(haystack)
    hits = sum(1 for token in dict.fromkeys(needles) if token in hay)
    return min(max_points, hits * 5)


def _tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9+#./-]{2,}|[\u4e00-\u9fff]{2,}", text or "")]
    return [token for token in tokens if not re.fullmatch(r"20\d{2}", token)]


def _contains_any(text: str, words: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(word.lower() in lowered for word in words if word)


def _company_terms(job: Job) -> list[str]:
    base = _core_company_name(job.company_normalized or job.company)
    terms = [job.company, job.company_normalized or "", base]
    for key, aliases in COMPANY_ALIASES.items():
        if key in (job.company_normalized or job.company) or key in base:
            terms.extend(aliases)
    return [term for term in dict.fromkeys(_clean(term) for term in terms) if term]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


COMPANY_ALIASES = {
    "米哈游": ["mihoyo", "hoyoverse"],
    "腾讯": ["tencent", "qq.com", "join.qq.com"],
    "欧莱雅": ["loreal", "l'oréal"],
    "京东方": ["boe"],
    "大疆": ["dji"],
    "高盛": ["goldman", "gs.com"],
    "恩智浦": ["nxp"],
    "SharkNinja": ["sharkninja"],
    "智元": ["agibot", "zhiyuan"],
    "自变量": ["x2robot"],
    "天翼云": ["ctyun"],
    "趣加": ["funplus"],
    "微步在线": ["threatbook"],
    "元戎启行": ["deeproute"],
    "国泰海通": ["gtht", "gtja", "haitong"],
    "航天科工": ["casic"],
    "航天科技": ["spacechina", "casc"],
    "中国航发": ["aecc"],
}


def _core_company_name(company: str) -> str:
    value = re.sub(r"[（(].*?[）)]", "", company or "")
    for prefix in (
        "上海市",
        "上海",
        "北京市",
        "北京",
        "深圳市",
        "深圳",
        "广州市",
        "广州",
        "杭州市",
        "杭州",
        "苏州市",
        "苏州",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    for suffix in (
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "网络科技",
        "网络",
        "科技",
        "集团",
        "控股",
        "中国",
    ):
        value = value.replace(suffix, "")
    return _clean(value)


class _SearchResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[OfficialCandidate] = []
        self._in_link = False
        self._in_h2 = False
        self._href = ""
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self._in_h2 = True
            return
        if tag == "h3":
            self._in_h2 = True
            return
        if tag != "a":
            return
        if not self._in_h2:
            return
        attr = {key: value or "" for key, value in attrs}
        href = attr.get("href", "")
        if not href:
            return
        url = _normalize_result_url(href)
        if not url or not url.startswith(("http://", "https://")):
            return
        self._in_link = True
        self._href = url
        self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            text = _clean(data)
            if text:
                self._title_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h2", "h3"}:
            self._in_h2 = False
            return
        if tag != "a" or not self._in_link:
            return
        title = _clean(" ".join(self._title_parts))
        if title and self._href and not _is_noise_url(self._href):
            candidate = OfficialCandidate(url=self._href, title=title, source="search")
            if candidate.url not in {item.url for item in self.results}:
                self.results.append(candidate)
        self._in_link = False
        self._href = ""
        self._title_parts = []


def _normalize_result_url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("/url?") or href.startswith("https://www.google.com/url?"):
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        target = query.get("q") or query.get("url")
        if target:
            return unquote(target[0])
    parsed = urlparse(href)
    if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
        target = parse_qs(parsed.query).get("u")
        if target:
            decoded = _decode_bing_url(target[0])
            if decoded:
                return decoded
    return href


def _decode_bing_url(value: str) -> str:
    raw = value[2:] if value.startswith("a1") else value
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(f"{raw}{padding}").decode("utf-8")
    except Exception:
        return ""


def _is_noise_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(noise in host for noise in ["bing.com", "google.com", "baidu.com"])
