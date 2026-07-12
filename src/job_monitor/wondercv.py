from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
import random
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

import requests

from .models import Job
from .normalizer import build_dedupe_key, infer_batch, infer_city, infer_graduate_year, normalize_company, normalize_date


WONDERCV_URL = "https://www.wondercv.com/xiaozhao/"
EXTRACTION_VERSION = "detail-structure-v1"


def _print_progress(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True, slots=True)
class CrawlResult:
    jobs: list[Job]
    pages_scanned: int
    partial: bool = False
    error: str | None = None
    interrupted: bool = False


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
            return CrawlResult(jobs=jobs, pages_scanned=pages_scanned)
        except Exception as exc:
            if isinstance(exc, ScanInterrupted):
                return CrawlResult(jobs=jobs, pages_scanned=pages_scanned, error="日常扫描已中断", interrupted=True)
            return CrawlResult(jobs=jobs, pages_scanned=pages_scanned, partial=bool(jobs), error=str(exc))

    def crawl_pages(self, mode: str = "daily", should_stop: Callable[[list[Job]], bool] | None = None):
        crawler_config = self.config.get("crawler", {})
        max_pages = int(crawler_config.get("max_pages_init" if mode == "init" else "max_pages_daily", 20))
        import logging
        for page in range(1, max_pages + 1):
            self._ensure_not_cancelled()
            page_url = self._page_url(page)
            self.progress(f"抓取列表：第 {page}/{max_pages} 页")
            try:
                response = self.get(page_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
            except Exception as exc:
                logging.error("Failed to fetch page %s: %s", page, exc)
                raise RuntimeError(f"WonderCV 第 {page} 页抓取失败：{exc}") from exc
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
    for keyword in DETAIL_KEYWORDS:
        if _detail_keyword_in_text(text, keyword):
            hits.append(keyword)
    return hits


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
            elif classes & {"date", "time", "collect-date", "created-at"}:
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
