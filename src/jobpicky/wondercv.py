from __future__ import annotations

import hashlib
import json
import logging
from html.parser import HTMLParser
import random
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

import requests

from .models import Job, Position
from .normalizer import build_dedupe_key, infer_batch, infer_city, infer_graduate_year, normalize_company, normalize_date
from .error_safety import safe_exception_detail
from .taxonomy import infer_role_direction, role_signal_terms


WONDERCV_URL = "https://www.wondercv.com/xiaozhao/"
EXTRACTION_VERSION = "detail-structure-v2"


def _print_progress(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True, slots=True)
class CrawlResult:
    jobs: list[Job]
    pages_scanned: int
    partial: bool = False
    error: str | None = None
    interrupted: bool = False
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0


class ScanInterrupted(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DetailParseResult:
    raw_text: str
    apply_url: str | None = None
    keywords: list[str] | None = None
    summary: str = ""
    city: str | None = None
    degree: str | None = None
    deadline: str | None = None
    batch: str | None = None
    graduate_year: str | None = None
    role_text: str = ""
    announcement_text: str = ""
    role_signals: list[str] | None = None
    field_evidence: dict[str, dict[str, object]] | None = None
    positions: list[Position] | None = None


def parse_wondercv_list(html: str, page_url: str, aliases: dict[str, list[str]] | None = None) -> list[Job]:
    text = _strip_tags(html)
    if ("验证码" in text or "请登录" in text) and len(text) < 1000:
        raise RuntimeError("WonderCV 公开页面受限，出现登录或验证码提示")

    cards = _CardParser.parse(html)
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    for card in cards:
        detail_url = urljoin(page_url, card.href)
        source_job_id = _extract_job_id(detail_url)
        if not source_job_id:
            continue
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)

        raw_title = _clean(card.title or card.text)
        if not raw_title or len(raw_title) < 4:
            continue

        parsed = _parse_card_text(raw_title)
        title = parsed["clean_title"]
        company = card.company or parsed["company"] or _infer_company(title)
        city = card.city or infer_city(raw_title)
        # WonderCV currently uses ``card-date`` but the visible card text is a
        # stable fallback when the site's presentation class changes again.
        date_text = card.date or raw_title
        tags = card.tags or parsed["raw_tags"]
        company_normalized = normalize_company(company, aliases)
        collected_date = normalize_date(date_text)
        batch = infer_batch(raw_title)
        dedupe_key = build_dedupe_key(
            source="WonderCV",
            source_job_id=source_job_id,
            detail_url=detail_url,
            company_normalized=company_normalized,
            title=title,
            batch=batch,
            collected_date=collected_date,
        )
        jobs.append(
            Job(
                source="WonderCV",
                source_job_id=source_job_id,
                source_url=page_url,
                detail_url=detail_url,
                dedupe_key=dedupe_key,
                company=company,
                raw_company=company,
                company_normalized=company_normalized,
                title=title,
                raw_title=raw_title,
                clean_title=title,
                summary=parsed["summary"],
                batch=batch,
                target_graduate_year=infer_graduate_year(raw_title),
                city=city,
                location_text=city,
                collected_date=collected_date,
                company_type=parsed["company_type"],
                industry=parsed["industry"],
                tags=tags,
                job_tags=parsed["job_tags"],
                special_marks=parsed["special_marks"],
                raw_tags=parsed["raw_tags"],
                raw_text=raw_title,
                parse_status="list_only",
                parse_note="" if title else "clean title missing",
            )
        )
    return jobs


def parse_wondercv_detail(html: str) -> DetailParseResult:
    html_without_noise = _remove_noise_blocks(html)
    text = _trim_detail_tail(_focus_detail_body(_strip_tags(html_without_noise)))
    important_text = _extract_detail_signal_text(text)
    role_text = important_text or ""
    keywords = _extract_detail_keywords(role_text)
    apply_url = _extract_apply_url(html)
    summary_source = _clean(f"{text[:220]} {important_text}") if important_text else text
    summary = _clean(summary_source[:500])
    city = infer_city(role_text or text)
    degree = _extract_degree(role_text or text)
    deadline = _extract_deadline(text)
    batch = infer_batch(text)
    graduate_year = infer_graduate_year(text)
    evidence = _field_evidence(
        city=city,
        degree=degree,
        deadline=deadline,
        batch=batch,
        graduate_year=graduate_year,
        role_text=role_text,
    )
    positions = _extract_detail_positions(html_without_noise, role_text)
    return DetailParseResult(
        raw_text=text,
        apply_url=apply_url,
        keywords=keywords,
        summary=summary,
        city=city,
        degree=degree,
        deadline=deadline,
        batch=batch,
        graduate_year=graduate_year,
        role_text=role_text,
        announcement_text=text,
        role_signals=keywords,
        field_evidence=evidence,
        positions=positions,
    )


class WonderCVCrawler:
    def __init__(
        self,
        config: dict,
        get: Callable[..., requests.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        progress: Callable[[str], None] = _print_progress,
        cancel_check: Callable[[], bool] | None = None,
    ):
        self.config = config
        self.get = get or requests.get
        self.sleep = sleep
        self.progress = progress
        self.cancel_check = cancel_check or (lambda: False)
        self.aliases = config.get("system_taxonomy", {}).get("company_aliases", {})

    def crawl(self, mode: str = "daily", should_stop: Callable[[list[Job]], bool] | None = None) -> CrawlResult:
        jobs: list[Job] = []
        pages_scanned = 0
        try:
            for page_jobs in self.crawl_pages(mode, should_stop=should_stop):
                pages_scanned += 1
                jobs.extend(page_jobs)
            return CrawlResult(
                jobs=jobs,
                pages_scanned=pages_scanned,
                sources_attempted=1,
                sources_succeeded=1,
            )
        except Exception as exc:
            if isinstance(exc, ScanInterrupted):
                return CrawlResult(jobs=jobs, pages_scanned=pages_scanned, error="日常扫描已中断", interrupted=True)
            return CrawlResult(
                jobs=jobs,
                pages_scanned=pages_scanned,
                partial=bool(jobs),
                error=safe_exception_detail(exc, self.config),
                sources_attempted=1,
                sources_succeeded=int(bool(pages_scanned or jobs)),
                sources_failed=1,
            )

    def crawl_pages(self, mode: str = "daily", should_stop: Callable[[list[Job]], bool] | None = None):
        crawler_config = self.config.get("crawler", {})
        max_pages = int(crawler_config.get("max_pages_init" if mode == "init" else "max_pages_daily", 20))
        for page in range(1, max_pages + 1):
            self._ensure_not_cancelled()
            page_url = self._page_url(page)
            self.progress(f"抓取列表：第 {page}/{max_pages} 页")
            try:
                response = self.get(page_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
            except Exception as exc:
                logging.error("Failed to fetch page %s: %s", page, safe_exception_detail(exc, self.config))
                safe_error = safe_exception_detail(exc, self.config)
                raise RuntimeError(f"WonderCV 第 {page} 页抓取失败：{safe_error}") from None
            page_jobs = parse_wondercv_list(response.text, page_url, self.aliases)
            self._ensure_not_cancelled()
            if not page_jobs:
                self.progress(f"第 {page} 页没有岗位，扫描完成。")
                break
            # The stop rule only depends on list-page fields.  Evaluate it before
            # detail requests so a fully known page does not spend minutes
            # re-fetching detail pages which will be discarded anyway.
            if should_stop and should_stop(page_jobs):
                self.progress(f"第 {page} 页均为已处理岗位，日常扫描完成。")
                break
            if self._enrich_details_enabled():
                self.progress(f"第 {page} 页发现 {len(page_jobs)} 个岗位，开始回填详情。")
                enriched_jobs: list[Job] = []
                for index, job in enumerate(page_jobs, start=1):
                    self._ensure_not_cancelled()
                    label = _clean(f"{job.company} {job.title}")[:36]
                    self.progress(f"详情回填：第 {page} 页 {index}/{len(page_jobs)} - {label}")
                    enriched = self.enrich_detail(job)
                    self._ensure_not_cancelled()
                    state = "完成" if enriched.parse_status == "detail_ready" else "未完整"
                    self.progress(f"详情回填：第 {page} 页 {index}/{len(page_jobs)} - {state}")
                    enriched_jobs.append(enriched)
                page_jobs = enriched_jobs
            else:
                self.progress(f"第 {page} 页发现 {len(page_jobs)} 个岗位。")
            yield page_jobs

    def _ensure_not_cancelled(self) -> None:
        if self.cancel_check():
            raise ScanInterrupted()
            self._pause()

    def enrich_detail(self, job: Job) -> Job:
        if not job.detail_url:
            return job
        try:
            timeout = float(self.config.get("crawler", {}).get("detail_timeout_seconds", 20))
            response = self.get(job.detail_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            detail = parse_wondercv_detail(response.text)
        except Exception as exc:
            job.parse_status = "detail_failed"
            note = f"detail fetch failed: {exc}"
            job.parse_note = "; ".join(part for part in [job.parse_note, note] if part)
            return job
        if not detail.raw_text:
            job.parse_status = "detail_failed"
            job.parse_note = "; ".join(part for part in [job.parse_note, "detail fetch empty"] if part)
            return job
        merge_detail_into_job(job, detail)
        self._detail_pause()
        return job
    def _page_url(self, page: int) -> str:
        if page <= 1:
            return WONDERCV_URL
        return f"{WONDERCV_URL}page/pn{page}/"

    def _pause(self) -> None:
        cfg = self.config.get("crawler", {})
        low = float(cfg.get("min_interval_seconds", 2))
        high = float(cfg.get("max_interval_seconds", 5))
        self.sleep(random.uniform(low, high))

    def _detail_pause(self) -> None:
        cfg = self.config.get("crawler", {})
        low = float(cfg.get("detail_min_interval_seconds", cfg.get("min_interval_seconds", 2)))
        high = float(cfg.get("detail_max_interval_seconds", cfg.get("max_interval_seconds", 5)))
        self.sleep(random.uniform(low, high))

    def _enrich_details_enabled(self) -> bool:
        value = self.config.get("crawler", {}).get("enrich_details", True)
        return value not in (False, "false", "False", 0, "0")


def merge_detail_into_job(job: Job, detail: DetailParseResult) -> Job:
    """Apply one successful detail parse using the authoritative field policy."""
    job.raw_text = detail.raw_text
    job.apply_url = urljoin(job.detail_url, detail.apply_url) if detail.apply_url else job.apply_url
    job.content_hash = hashlib.sha256(detail.raw_text.encode("utf-8")).hexdigest()
    job.role_text = detail.role_text
    job.announcement_text = detail.announcement_text
    job.role_signals = detail.role_signals or []
    job.field_evidence = json.dumps(detail.field_evidence or {}, ensure_ascii=False, sort_keys=True)
    job.extraction_version = EXTRACTION_VERSION
    job.positions = detail.positions or []
    job.job_tags = _non_detail_tags(job.job_tags)
    if detail.summary:
        job.summary = detail.summary
    if detail.graduate_year:
        job.target_graduate_year = detail.graduate_year
    if detail.city:
        job.city = detail.city
        job.location_text = detail.city
    if detail.degree:
        job.degree = detail.degree
    if detail.deadline:
        job.deadline = detail.deadline
    if detail.batch:
        job.batch = detail.batch
    job.parse_status = "detail_ready"
    return job


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_tags(html: str) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", html))


DETAIL_SIGNAL_MARKERS = [
    "招聘岗位",
    "关联岗位",
    "岗位要求",
    "职位摘要",
    "招聘方向",
    "岗位方向",
    "岗位信息",
]

DETAIL_SECTION_END_MARKERS = [
    "招聘流程",
    "投递建议",
    "福利待遇",
    "常见问题",
    "FAQ",
    "公司介绍",
    "申请方式",
]

DETAIL_KEYWORDS = [
    "嵌入式",
    "GNSS",
    "图像算法",
    "测试开发",
    "流体力学",
    "FPGA",
    "IC",
    "数字电路",
    "模拟电路",
    "芯片",
    "半导体",
    "Verilog",
    "PCB",
    "C/C++",
    "RTOS",
    "Linux",
    "单片机",
    "驱动开发",
    "算法",
    "硬件",
    "软件",
    "技术",
    "产品",
    "运营",
    "数据",
    "研发",
]

POSITION_TITLE_TERMS = (
    "工程师", "研究员", "研究助理", "科研人员", "助理", "经理", "专员", "顾问", "设计师", "架构师",
    "管培生", "培训生", "实习生", "实习岗", "教师", "辅导员", "代表", "HRBP",
)
POSITION_ENGLISH_TERMS = re.compile(
    r"\b(?:engineer|researcher|intern|manager|developer|designer|consultant|specialist|sales|hrbp)\b",
    re.I,
)
POSITION_REJECT_PREFIXES = (
    "负责", "参与", "协助", "完成", "支持", "开展", "承担", "进行", "编写", "制定", "跟进",
    "配合", "根据", "提供", "协同", "推动", "维护", "实现", "具备", "熟悉", "掌握", "要求",
    "独立完成", "主导", "搭建", "收集", "深入了解", "定期", "候选人",
)
POSITION_LIST_LABELS = ("类", "岗位", "方向", "地点", "城市", "类别")
POSITION_SUMMARY_TERMS = ("运营", "财务", "审计", "采购", "销售", "教练", "编辑", "律师")


def _extract_detail_signal_text(text: str) -> str:
    snippets: list[str] = []
    for marker in DETAIL_SIGNAL_MARKERS:
        start = text.find(marker)
        if start < 0:
            continue
        end = len(text)
        for next_marker in DETAIL_SIGNAL_MARKERS:
            if next_marker == marker:
                continue
            next_index = text.find(next_marker, start + len(marker))
            if next_index > start:
                end = min(end, next_index)
        for end_marker in DETAIL_SECTION_END_MARKERS:
            end_index = text.find(end_marker, start + len(marker))
            if end_index > start:
                end = min(end, end_index)
        snippets.append(text[start : min(end, start + 1600)])
    return _clean(" ".join(snippets))


def _trim_detail_tail(text: str) -> str:
    candidates = []
    for marker in ("校招推荐", "文章推荐", "©202", "京ICP备"):
        index = text.find(marker)
        if index >= 0:
            candidates.append(index)
    if not candidates:
        return text
    first_tail = min(candidates)
    if first_tail <= 80:
        later = [index for index in candidates if index > 80]
        if later:
            first_tail = min(later)
    return _clean(text[:first_tail])


def _focus_detail_body(text: str) -> str:
    starts = [text.find(marker) for marker in ("首页 / 校招信息", "招聘公告与岗位信息") if text.find(marker) >= 0]
    if not starts:
        return text
    focused = _clean(text[min(starts):])
    import re
    cleaned = re.sub(r'^首页\s*/\s*校招信息(?:\s*/\s*[^/]+){1,2}\s*/\s*', '', focused)
    return _clean(cleaned)


def _extract_detail_keywords(text: str) -> list[str]:
    hits: list[str] = []
    for keyword in dict.fromkeys([*DETAIL_KEYWORDS, *role_signal_terms()]):
        if _detail_keyword_in_text(text, keyword):
            hits.append(keyword)
    return hits


def _extract_detail_positions(html: str, role_text: str) -> list[Position]:
    blocks = _role_section_blocks(_extract_block_texts(html))
    if not blocks and role_text:
        blocks = [role_text]
    elif role_text:
        blocks = [*_related_position_title_blocks(role_text), *blocks]
    positions: list[Position] = []
    positions_by_title: dict[str, Position] = {}
    current: Position | None = None
    for block in blocks:
        candidates = _position_candidates(block)
        if candidates:
            for title, tail, location_hint in candidates:
                city = infer_city(location_hint or block)
                candidate = Position(
                    title=title,
                    direction_id=infer_role_direction(f"{title} {tail}"),
                    employment_type=_extract_employment_type(block),
                    city=city,
                    location_status="confirmed" if city else "pending",
                    degree=_extract_degree(block),
                    majors=_extract_majors(block),
                    responsibilities=tail or None,
                    skills=_extract_detail_keywords(block),
                    headcount=_extract_headcount(block),
                    source_text=block,
                    field_evidence={"title": {"source": "detail_role_block", "evidence": block[:240]}},
                    confidence=0.94 if tail else 0.88,
                    extraction_version="position-v1",
                    ordinal=len(positions),
                )
                key = _normalized_position_title(title)
                current = positions_by_title.get(key)
                if current is None:
                    current = candidate
                    positions_by_title[key] = current
                    positions.append(current)
                else:
                    _merge_position(current, candidate)
            continue
        if current is None:
            continue
        current.source_text = _clean(f"{current.source_text} {block}")
        current.skills = _merge_unique(current.skills, _extract_detail_keywords(block))
        current.degree = current.degree or _extract_degree(block)
        current.majors = _merge_unique(current.majors, _extract_majors(block))
        current.headcount = current.headcount or _extract_headcount(block)
        if not current.city:
            current.city = infer_city(block)
            current.location_status = "confirmed" if current.city else "pending"
        if re.match(r"^(?:岗位职责|工作职责|职位职责|职责)[：:]?", block):
            current.responsibilities = _clean(re.sub(r"^(?:岗位职责|工作职责|职位职责|职责)[：:]?", "", block))
        elif re.match(r"^(?:岗位要求|任职要求|职位要求|任职资格|要求)[：:]?", block):
            current.requirements = _clean(re.sub(r"^(?:岗位要求|任职要求|职位要求|任职资格|要求)[：:]?", "", block))
        elif current.requirements:
            current.requirements = _clean(f"{current.requirements} {block}")
    for ordinal, position in enumerate(positions):
        position.ordinal = ordinal
        for field_name in ("city", "degree", "majors", "responsibilities", "requirements", "skills", "headcount"):
            value = getattr(position, field_name)
            if value not in (None, "", []):
                position.field_evidence[field_name] = {
                    "source": "detail_role_block",
                    "evidence": (position.source_text or "")[:240],
                }
    return positions


def _position_candidates(block: str) -> list[tuple[str, str, str]]:
    text = _clean(re.sub(r"^(?:[-•·🎯📍]\s*|\d{1,3}[.、)）]\s*)", "", block))
    if not text:
        return []
    colon = re.match(r"^(?P<label>[^：:]{1,40})\s*[：:]\s*(?P<body>.+)$", text)
    if colon:
        label = _clean(colon.group("label"))
        body = _clean(colon.group("body"))
        title = _clean_position_title(label)
        if title:
            return [(title, body, label)]
        if label.endswith(("地点", "城市")):
            return []
        if infer_city(label) or label.endswith(POSITION_LIST_LABELS):
            return _position_list_candidates(body, location_hint=label if infer_city(label) else "", allow_plain=True)
        return []

    sentence = re.match(r"^(?P<title>[^，。]{2,32})，(?P<tail>(?:负责|参与|承担|涵盖|工作地点).+)$", text)
    if sentence:
        title = _clean_position_title(sentence.group("title"), allow_plain=True)
        if title and (_has_position_signal(title) or title.endswith(POSITION_SUMMARY_TERMS)):
            return [(title, _clean(sentence.group("tail")), title)]
    parts = re.split(r"[、；;]", text)
    if len(parts) > 1:
        candidates = _position_list_candidates(text)
        if len(candidates) > 1:
            return candidates
    title = _clean_position_title(text)
    return [(title, "", text)] if title else []


def _related_position_title_blocks(role_text: str) -> list[str]:
    terms = "|".join(re.escape(term) for term in sorted(POSITION_TITLE_TERMS, key=len, reverse=True))
    titles: list[str] = []
    for marker in ("关联岗位", "招聘岗位"):
        match = re.search(rf"{marker}\s+(?P<title>.{{0,40}}?(?:{terms}))(?=\s)", role_text)
        if match:
            title = _clean_position_title(match.group("title"))
            if title and title not in titles:
                titles.append(title)
    for match in re.finditer(r"(?:本次)?招聘岗位为\s*([^。，]{2,60})", role_text):
        for value in re.split(r"[、和]", match.group(1)):
            title = _clean_position_title(value, allow_plain=True)
            if title and len(title) <= 20 and title not in titles:
                titles.append(title)
    return titles


def _position_list_candidates(
    text: str, *, location_hint: str = "", allow_plain: bool = False
) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    parts = re.split(r"[、；;]", text)
    if allow_plain and not any(_clean_position_title(part) for part in parts):
        return []
    for part in parts:
        title = _clean_position_title(part, allow_plain=allow_plain)
        if title:
            candidates.append((title, "", location_hint))
    return candidates


def _clean_position_title(value: str, *, allow_plain: bool = False) -> str:
    title = _clean(value).strip("-—–·• ")
    if not title or title.startswith(POSITION_REJECT_PREFIXES):
        return ""
    if re.match(r"^[（(]?[一二三四五六七八九十0-9]+[）).、]", title):
        return ""
    for inner in reversed(re.findall(r"[（(]([^）)]{2,40})[）)]", title)):
        if POSITION_ENGLISH_TERMS.search(title) and _has_position_signal(inner):
            title = _clean(inner)
            break
    trailing = re.search(r"\s*[-—–]\s*([^—–-]{2,12})$", title)
    if trailing and infer_city(trailing.group(1)):
        title = _clean(title[: trailing.start()])
    location = re.search(r"[（(]([^）)]{2,20})[）)]$", title)
    if location and (infer_city(location.group(1)) or "岗位详情" in location.group(1)):
        title = _clean(title[: location.start()])
    if not title or len(title) > 36 or title.startswith(POSITION_REJECT_PREFIXES):
        return ""
    if any(mark in title for mark in "，。；;：:！？→"):
        return ""
    if title in {"岗位", "职位", "招聘岗位", "关联岗位", "岗位信息", "专业要求", "技能要求"}:
        return ""
    if not allow_plain and not _has_position_signal(title):
        return ""
    if allow_plain and len(title) > 24:
        return ""
    return title


def _has_position_signal(title: str) -> bool:
    base = re.sub(r"[（(][^）)]{1,40}[）)]\s*$", "", title).strip()
    if base in {"开发", "测试", "算法", "助理", "经理", "专员", "顾问", "教师", "代表"}:
        return False
    return base.endswith(POSITION_TITLE_TERMS) or bool(POSITION_ENGLISH_TERMS.search(base))


def _normalized_position_title(title: str) -> str:
    return re.sub(r"[\s·•]+", "", title).casefold()


def _merge_position(target: Position, incoming: Position) -> None:
    target.city = _merge_delimited(target.city, incoming.city)
    target.location_status = "confirmed" if target.city else "pending"
    target.degree = target.degree or incoming.degree
    target.majors = _merge_unique(target.majors, incoming.majors)
    target.skills = _merge_unique(target.skills, incoming.skills)
    target.headcount = target.headcount or incoming.headcount
    target.responsibilities = target.responsibilities or incoming.responsibilities
    target.requirements = target.requirements or incoming.requirements
    if incoming.source_text and incoming.source_text not in (target.source_text or ""):
        target.source_text = _clean(f"{target.source_text} {incoming.source_text}")


def _merge_delimited(left: str | None, right: str | None) -> str | None:
    values: list[str] = []
    for item in [*(left or "").split(";"), *(right or "").split(";")]:
        if item and item not in values:
            values.append(item)
    return ";".join(values) or None


def _extract_block_texts(html: str) -> list[str]:
    blocks: list[str] = []
    pattern = r"<(?:h[1-6]|p|li|dt|dd|td|th)\b[^>]*>([\s\S]*?)</(?:h[1-6]|p|li|dt|dd|td|th)>"
    for match in re.finditer(pattern, html, re.I):
        text = _strip_tags(match.group(1))
        if text and text not in blocks:
            blocks.append(text)
    if blocks:
        return blocks
    line_html = re.sub(r"<(?:br|/p|/li|/div|/section|/h[1-6])\b[^>]*>", "\n", html, flags=re.I)
    return [_clean(_strip_tags(line)) for line in line_html.splitlines() if _clean(_strip_tags(line))]


def _role_section_blocks(blocks: list[str]) -> list[str]:
    selected: list[str] = []
    active = False
    for block in blocks:
        heading = _clean(re.sub(r"^[^\w\u4e00-\u9fff]+", "", block))
        if active and any(heading == marker or heading.startswith(f"{marker}：") for marker in DETAIL_SECTION_END_MARKERS):
            break
        wrapper = heading == "招聘公告与岗位信息"
        marker = next(
            (item for item in DETAIL_SIGNAL_MARKERS if heading == item or heading.startswith(f"{item}：")),
            None,
        )
        if wrapper or marker:
            active = True
            remainder = "" if wrapper else _clean(heading[len(marker or "") :].lstrip("：: "))
            if remainder:
                selected.append(remainder)
            continue
        if active:
            selected.append(block)
    return selected


def _extract_employment_type(text: str) -> str | None:
    if "实习" in text:
        return "实习"
    if any(term in text for term in ("校招", "应届", "校园招聘")):
        return "校招"
    if any(term in text for term in ("社招", "社会招聘")):
        return "社招"
    return None


def _extract_majors(text: str) -> list[str]:
    match = re.search(r"(?:专业要求|专业)[：:]?\s*([^。；;]{2,100})", text or "")
    if not match:
        return []
    return [part.strip() for part in re.split(r"[、,/，及或]+", match.group(1)) if part.strip()]


def _extract_headcount(text: str) -> int | None:
    match = re.search(r"(?:招聘|招募|人数)[^0-9]{0,6}(\d{1,4})\s*人", text or "")
    return int(match.group(1)) if match else None


def _field_evidence(
    *,
    city: str | None,
    degree: str | None,
    deadline: str | None,
    batch: str | None,
    graduate_year: str | None,
    role_text: str,
) -> dict[str, dict[str, object]]:
    """Record enough provenance to explain why detail values win over card values."""
    values = {
        "city": (city, "detail_role_text" if city and city in role_text else "detail_body"),
        "degree": (degree, "detail_role_text" if degree and degree in role_text else "detail_body"),
        "deadline": (deadline, "detail_body"),
        "batch": (batch, "detail_body"),
        "target_graduate_year": (graduate_year, "detail_body"),
    }
    evidence: dict[str, dict[str, object]] = {}
    for name, (value, source) in values.items():
        if value:
            text = role_text if source == "detail_role_text" else "详情页正文"
            evidence[name] = {
                "value": value,
                "source": source,
                "evidence": text[:240],
                "confidence": 0.95 if source == "detail_role_text" else 0.9,
            }
    return evidence


def _detail_keyword_in_text(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    if keyword == "IC":
        return bool(re.search(r"(?<![A-Za-z0-9_])IC(?![A-Za-z0-9_])", text, flags=re.I)) or bool(
            re.search(r"(?<![A-Za-z0-9_])IC(?=[\u4e00-\u9fff])", text, flags=re.I)
        )
    return keyword.lower() in text.lower()


def _remove_noise_blocks(html: str) -> str:
    cleaned = html
    for tag in ("script", "style", "noscript", "nav", "header", "footer", "aside"):
        cleaned = re.sub(rf"<{tag}\b[\s\S]*?</{tag}>", " ", cleaned, flags=re.I)
    return cleaned


def _extract_apply_url(html: str) -> str | None:
    for match in re.finditer(r"<a\b([^>]*)>([\s\S]*?)</a>", html, re.I):
        attrs, body = match.groups()
        href_match = re.search(r"href=['\"]([^'\"]+)['\"]", attrs, re.I)
        if not href_match:
            continue
        href = href_match.group(1)
        label = _strip_tags(body)
        if "投递" in label or re.search(r"(jobs|apply|campus|zhaopin)", href, re.I):
            return href
    match = re.search(r"<a[^>]+href=['\"]([^'\"]*(?:jobs|apply|campus|zhaopin)[^'\"]*)['\"]", html, re.I)
    return match.group(1) if match else None


def _extract_degree(text: str) -> str | None:
    for degree in ("博士", "硕士", "本科及以上", "本科", "大专", "MBA"):
        if degree in (text or ""):
            return degree
    return None


def _extract_deadline(text: str) -> str | None:
    for pattern in (
        r"截止时间\s*(20\d{2})[-./](\d{1,2})[-./](\d{1,2})",
        r"截止[^0-9]*(20\d{2})[-./](\d{1,2})[-./](\d{1,2})",
    ):
        match = re.search(pattern, text or "")
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    values: list[str] = []
    for item in [*left, *right]:
        if item and item not in values:
            values.append(item)
    return values


def _non_detail_tags(tags: list[str]) -> list[str]:
    detail_keywords = set(DETAIL_KEYWORDS)
    return [tag for tag in tags if tag not in detail_keywords]


def _infer_company(title: str) -> str:
    for sep in (" 202", "202", "校园招聘", "秋招", "提前批"):
        if sep in title:
            return title.split(sep)[0].strip()
    return title[:30]


COMPANY_TYPES = {"上市公司", "央企国企", "民企", "外企", "合资", "事业单位", "政府机关", "社会组织", "其他"}
SPECIAL_MARKS = {"有内推"}
DEGREES = {"大专", "本科", "硕士", "博士", "MBA"}
BATCH_WORDS = {"秋招提前批", "秋招", "秋招补录", "春招提前批", "春招", "春招补录", "暑期实习", "寒假实习"}


def _parse_card_text(text: str) -> dict[str, object]:
    tokens = text.split()
    company_type = tokens[0] if tokens and tokens[0] in COMPANY_TYPES else ""
    industry = ""
    special_marks: list[str] = []
    raw_tags: list[str] = []
    prefix_end = 0

    for index, token in enumerate(tokens):
        if token == "收录":
            prefix_end = index + 2 if index + 1 < len(tokens) else index + 1
            break
        if index == 1 and company_type:
            industry = token
        if token in SPECIAL_MARKS:
            special_marks.append(token)
        if index <= 3:
            raw_tags.append(token)

    rest = tokens[prefix_end:] if prefix_end else tokens
    company = rest[0] if rest else ""
    after_company = rest[1:] if len(rest) > 1 else []
    clean_tokens: list[str] = []
    job_tags: list[str] = []
    metadata_started = False
    for token in after_company:
        if token in DEGREES or token in BATCH_WORDS:
            raw_tags.append(token)
            metadata_started = True
            continue
        if infer_city(token):
            raw_tags.append(token)
            metadata_started = True
            continue
        if metadata_started:
            job_tags.append(token)
            continue
        if len(clean_tokens) < 12:
            clean_tokens.append(token)
        else:
            job_tags.append(token)

    clean_title = _clean(" ".join(clean_tokens)) or company or text
    summary = _clean(" ".join(after_company))[:300] if after_company else clean_title
    job_tags = [tag for tag in job_tags if tag not in raw_tags]
    return {
        "company_type": company_type,
        "industry": industry,
        "company": company,
        "clean_title": clean_title[:160],
        "summary": summary,
        "special_marks": special_marks,
        "job_tags": job_tags[:10],
        "raw_tags": [tag for tag in raw_tags if tag],
    }


def _extract_job_id(url: str) -> str | None:
    match = re.search(r"/xiaozhao/([^/?#]+)", url)
    if not match:
        return None
    value = match.group(1).strip("/")
    return value or None


class _Card:
    def __init__(self, href: str):
        self.href = href
        self.text_parts: list[str] = []
        self.title = ""
        self.company = ""
        self.city = ""
        self.date = ""
        self.tags: list[str] = []

    @property
    def text(self) -> str:
        return _clean(" ".join(self.text_parts))


class _CardParser(HTMLParser):
    CARD_CLASSES = {"job-card", "position-card", "school-recruit-card"}

    def __init__(self):
        super().__init__()
        self.cards: list[_Card] = []
        self.current: _Card | None = None
        self.current_field = ""
        self.depth = 0

    @classmethod
    def parse(cls, html: str) -> list[_Card]:
        parser = cls()
        parser.feed(html)
        return parser.cards

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        href = attr.get("href", "")
        starts_card = href and "xiaozhao" in href and (tag == "a" or classes & self.CARD_CLASSES)
        if starts_card and self.current is None:
            self.current = _Card(href)
            self.depth = 1
        elif self.current is not None:
            self.depth += 1

        if self.current is not None:
            if tag in {"h1", "h2", "h3"} or classes & {"title", "job-title", "name"}:
                self.current_field = "title"
            elif classes & {"company", "company-name"} or "data-company" in attr:
                self.current_field = "company"
                if attr.get("data-company"):
                    self.current.company = attr["data-company"]
            elif classes & {"city", "work-city"} or "data-city" in attr:
                self.current_field = "city"
                if attr.get("data-city"):
                    self.current.city = attr["data-city"]
            elif classes & {"date", "time", "card-date", "collect-date", "created-at"}:
                self.current_field = "date"
            elif classes & {"tag", "label", "badge"}:
                self.current_field = "tag"

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        self.depth -= 1
        self.current_field = ""
        if self.depth <= 0:
            self.cards.append(self.current)
            self.current = None

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = _clean(data)
        if not text:
            return
        self.current.text_parts.append(text)
        if self.current_field == "title":
            self.current.title = _clean(f"{self.current.title} {text}")
        elif self.current_field == "company":
            self.current.company = _clean(f"{self.current.company} {text}")
        elif self.current_field == "city":
            self.current.city = _clean(f"{self.current.city} {text}")
        elif self.current_field == "date":
            self.current.date = _clean(f"{self.current.date} {text}")
        elif self.current_field == "tag":
            self.current.tags.append(text)
