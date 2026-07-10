from __future__ import annotations

from datetime import datetime
import re

from .models import Job, MatchResult
from .normalizer import infer_graduate_year, normalize_company


class Matcher:
    def __init__(self, config: dict):
        self.config = config
        self.profile = config.get("user_profile", {})
        self.taxonomy = config.get("system_taxonomy", {})
        self.company_aliases = self.taxonomy.get("company_aliases", {})

    def match(self, job: Job) -> MatchResult:
        text = self._job_text(job)
        negative_hits = self._negative_hits(text)
        role_negative_hits = self._negative_hits(self._job_role_text(job))
        city_hit = self._match_one(job.city or "", self.profile.get("target_cities", []))

        if not self._graduate_year_matches(job, text):
            return self._result(False, "届别不匹配", negative_hits=negative_hits, city_hit=city_hit)
        if not self._batch_matches(job, text):
            return self._result(False, "批次不匹配", negative_hits=negative_hits, city_hit=city_hit)
        if self._city_is_clear_mismatch(job, city_hit):
            return self._result(False, "城市不匹配", negative_hits=negative_hits, city_hit=city_hit)

        if role_negative_hits:
            return self._result(False, "命中排除岗位", negative_hits=role_negative_hits, city_hit=city_hit)

        company_hit = self._must_watch_company_hit(job)
        if company_hit:
            return self._result(
                True,
                "命中必看公司",
                score=100,
                matched_company=company_hit,
                negative_hits=negative_hits,
                city_hit=city_hit,
            )

        role_group, keyword_hits = self._role_group_hit(text)
        if role_group:
            return self._result(
                True,
                f"命中岗位方向：{role_group}",
                score=90,
                matched_keywords=keyword_hits,
                negative_hits=negative_hits,
                city_hit=city_hit,
            )

        industry_hit = self._target_industry_hit(job, text)
        generic_hits = self._match_many(text, self.taxonomy.get("generic_role_terms", []))
        if industry_hit and generic_hits and not negative_hits:
            return self._result(
                True,
                "目标行业下的研发/技术类岗位",
                score=70,
                matched_keywords=generic_hits,
                negative_hits=negative_hits,
                city_hit=city_hit,
            )

        return self._result(False, "", negative_hits=negative_hits, city_hit=city_hit)

    def _result(
        self,
        should_push: bool,
        reason: str,
        *,
        score: int = 0,
        matched_keywords: list[str] | None = None,
        matched_company: str = "",
        negative_hits: list[str] | None = None,
        city_hit: str | None = None,
        needs_verify: bool = False,
        verify_status: str = "未核验",
    ) -> MatchResult:
        return MatchResult(
            matched_keywords=matched_keywords or [],
            matched_strong_keywords=matched_keywords or [],
            matched_weak_keywords=[],
            matched_industry_keywords=[],
            matched_company_rule=matched_company,
            matched_city_rule=city_hit or "",
            negative_keywords=negative_hits or [],
            match_score=score,
            priority="push" if should_push else "skip",
            is_relevant=should_push,
            should_push=should_push,
            needs_verify=needs_verify,
            match_reason=reason,
            verify_status=verify_status,
            suggested_search_terms=[],
            match_config_version=str(self.config.get("profile", {}).get("version", "")),
            matched_at=datetime.now().isoformat(timespec="seconds"),
            recommend_reason=reason if should_push else "",
        )

    def _graduate_year_matches(self, job: Job, text: str) -> bool:
        expected = self.profile.get("graduate_years", [])
        if not expected:
            return True
        actual = job.target_graduate_year or infer_graduate_year(text)
        return not actual or self._contains_any(actual, expected)

    def _batch_matches(self, job: Job, text: str) -> bool:
        expected = self.profile.get("batches", [])
        if not expected:
            return True
        batch_text = " ".join(part for part in [job.batch or "", text] if part)
        if not batch_text.strip():
            return True
        return bool(self._match_many(batch_text, expected))

    def _city_is_clear_mismatch(self, job: Job, city_hit: str | None) -> bool:
        target_cities = self.profile.get("target_cities", [])
        return bool(target_cities and job.city and not city_hit)

    def _must_watch_company_hit(self, job: Job) -> str:
        company = normalize_company(job.company_normalized or job.company, self.company_aliases)
        return self._match_one(company, self.profile.get("must_watch_companies", [])) or ""

    def _role_group_hit(self, text: str) -> tuple[str, list[str]]:
        groups = self.taxonomy.get("role_groups", {})
        for group in self.profile.get("role_groups", []):
            hits = self._match_many(text, groups.get(group, []))
            if hits:
                return group, hits
        return "", []

    def _target_industry_hit(self, job: Job, text: str) -> str:
        haystack = " ".join(part for part in [job.industry or "", text] if part)
        return self._match_one(haystack, self.profile.get("target_industries", [])) or ""

    def _important_company_fallback(self, job: Job, text: str) -> bool:
        campus_terms = ["校园招聘", "校招", "秋招", "提前批", "实习", "春招"]
        if not self._match_many(text, campus_terms):
            return False
        company_type_hit = self._match_one(job.company_type or "", self.taxonomy.get("important_company_types", []))
        marks_text = " ".join(job.special_marks)
        mark_hit = self._match_one(marks_text, self.taxonomy.get("important_company_marks", []))
        return bool(company_type_hit or mark_hit)

    def _negative_hits(self, text: str) -> list[str]:
        groups = self.taxonomy.get("exclude_role_groups", {})
        hits: list[str] = []
        for group in self.profile.get("exclude_role_groups", []):
            hits.extend(self._match_many(text, groups.get(group, [])))
        return list(dict.fromkeys(hits))

    @staticmethod
    def _match_many(text: str, words: list[str]) -> list[str]:
        return [word for word in words if _keyword_in_text(text, word)]

    @staticmethod
    def _match_one(text: str, words: list[str]) -> str | None:
        for word in words:
            if _keyword_in_text(text, word):
                return word
        return None

    @staticmethod
    def _contains_any(text: str, words: list[str]) -> bool:
        return any(_keyword_in_text(text, word) for word in words)

    @staticmethod
    def _job_text(job: Job) -> str:
        return " ".join(
            part
            for part in [
                job.company,
                job.company_normalized or "",
                job.clean_title or job.title,
                job.summary or "",
                job.batch or "",
                job.city or "",
                job.industry or "",
                job.company_type or "",
                " ".join(job.tags),
                " ".join(job.job_tags),
                " ".join(job.special_marks),
                job.raw_text or "",
            ]
            if part
        )

    @staticmethod
    def _job_role_text(job: Job) -> str:
        return " ".join(
            part
            for part in [
                job.clean_title or job.title,
                " ".join(job.job_tags),
            ]
            if part
        )


def _keyword_in_text(text: str, word: str) -> bool:
    if not text or not word:
        return False
    if _is_short_ascii_keyword(word):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])"
        if re.search(pattern, text, flags=re.I):
            return True
        # Chinese job titles often attach short ASCII terms directly to CJK words,
        # e.g. IC验证工程师. Accept that while still rejecting public/service.
        cjk_attached = rf"(?<![A-Za-z0-9_]){re.escape(word)}(?=[\u4e00-\u9fff])"
        return bool(re.search(cjk_attached, text, flags=re.I))
    return word.lower() in text.lower()


def _is_short_ascii_keyword(word: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9+#./-]{1,3}", word))
