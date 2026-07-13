from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


_SENSITIVE_KEY = r"app[_-]?secret|access[_-]?token|auth(?:orization)?|bearer|webhook(?:_url)?|token|secret|signature|api[_-]?key|key"
_KEY_VALUE_RE = re.compile(
    rf"(?i)([\"']?\b(?:{_SENSITIVE_KEY})\b[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'&}}]+)"
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)(\b(?:app[_-]?secret|access[_-]?token|webhook(?:_url)?|signature)\b\s+)[^\s,;\"']+"
)
_AUTHORIZATION_RE = re.compile(r"(?i)(\bauthorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;\"']+")
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[^\s,;\"']+")
_QUERY_RE = re.compile(
    rf"(?i)([?&](?:{_SENSITIVE_KEY})=)[^&#\s,;\"']+"
)
_WEBHOOK_PATH_RE = re.compile(
    r"(?i)(https?://[^\s\"'<>]*?/(?:hooks?|webhooks?)/)[^?\s\"'<>]+"
)
_SAFE_FALLBACK = "发生内部错误，详细信息已隐藏"


def _safe_text(value: Any) -> str:
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
    except BaseException:
        return _SAFE_FALLBACK


def known_secrets(config: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Return configured secret-like values for centralized redaction."""
    try:
        if not isinstance(config, dict):
            return ()
        feishu = config.get("feishu", {})
        if not isinstance(feishu, dict):
            return ()
        values: list[str] = []
        for key in ("app_secret", "tenant_access_token", "webhook_url", "bitable_app_token", "app_id"):
            value = feishu.get(key)
            if value not in (None, ""):
                text = _safe_text(value)
                if text != _SAFE_FALLBACK:
                    values.append(text)
        return tuple(sorted(set(values), key=len, reverse=True))
    except BaseException:
        return ()


def _sub(pattern: re.Pattern[str], replacement: str, text: str) -> str:
    try:
        return pattern.sub(replacement, text)
    except BaseException:
        return text


def redact_text(value: Any, *, secrets: Iterable[str] = ()) -> str:
    """Redact credential-shaped text and never raise, even for hostile objects."""
    try:
        text = _safe_text(value)
        safe_secrets: list[str] = []
        try:
            for item in secrets:
                if item is None:
                    continue
                secret = _safe_text(item)
                if secret not in ("", _SAFE_FALLBACK):
                    safe_secrets.append(secret)
        except BaseException:
            pass
        for secret in sorted(set(safe_secrets), key=len, reverse=True):
            try:
                text = text.replace(secret, "[REDACTED]")
            except BaseException:
                pass
        text = _sub(_AUTHORIZATION_RE, r"\1[REDACTED]", text)
        text = _sub(_BEARER_RE, r"\1[REDACTED]", text)
        text = _sub(_QUERY_RE, r"\1[REDACTED]", text)
        text = _sub(_KEY_VALUE_RE, r"\1[REDACTED]", text)
        text = _sub(_NAMED_SECRET_RE, r"\1[REDACTED]", text)
        # Keep ordinary public job URLs readable. Only path tokens below a
        # webhook-like path are opaque credentials by convention.
        text = _sub(_WEBHOOK_PATH_RE, r"\1[REDACTED]", text)
        return text
    except BaseException:
        return _SAFE_FALLBACK


def safe_exception_detail(exc: BaseException, config: dict[str, Any] | None = None) -> str:
    """Return a log-safe exception type and message without a traceback."""
    try:
        type_name = _safe_text(type(exc).__name__)
    except BaseException:
        type_name = "Exception"
    try:
        raw = f"{type_name}: {_safe_text(exc)}"
    except BaseException:
        raw = f"{type_name}: {_SAFE_FALLBACK}"
    try:
        return redact_text(raw, secrets=known_secrets(config))
    except BaseException:
        return f"{type_name}: {_SAFE_FALLBACK}"
