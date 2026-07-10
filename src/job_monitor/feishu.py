from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests


RETRYABLE_CODES = frozenset({1254290, 1254291, 1254607, 1254608})


class FeishuApiError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    base_url: str = ""
    app_token: str = ""
    table_id: str = ""
    tenant_access_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FeishuConfig":
        feishu = config.get("feishu", {})
        base_url = str(feishu.get("base_url") or "")
        app_token = str(feishu.get("bitable_app_token") or "")
        if base_url:
            from .onboarding import parse_base_url

            app_token = parse_base_url(base_url).app_token
        return cls(
            base_url=base_url,
            app_token=app_token,
            table_id=feishu.get("workspace_table_id") or feishu.get("table_id", ""),
            tenant_access_token=feishu.get("tenant_access_token", ""),
            app_id=feishu.get("app_id", ""),
            app_secret=feishu.get("app_secret", ""),
            webhook_url=feishu.get("webhook_url", ""),
        )


@dataclass(frozen=True, slots=True)
class FeishuResult:
    sent: bool
    record_ids: list[str] = field(default_factory=list)
    error: str | None = None


class FeishuBitableClient:
    def __init__(
        self,
        config: FeishuConfig,
        post: Callable[..., Any] | None = None,
        get: Callable[..., Any] | None = None,
        put: Callable[..., Any] | None = None,
        patch: Callable[..., Any] | None = None,
        delete: Callable[..., Any] | None = None,
        *,
        max_retries: int = 3,
        sleep: Callable[[float], None] | None = None,
    ):
        self.config = config
        self.post = post or requests.post
        self.get = get or requests.get
        self.put = put or requests.put
        self.patch = patch or requests.patch
        self.delete = delete or requests.delete
        self.max_retries = max(max_retries, 0)
        self.sleep = sleep or time.sleep

    def get_app(self) -> dict[str, Any]:
        data = self._request_json("GET", self._api_url(""))
        return self._unwrap(data, "app")

    def list_tables(self) -> list[dict[str, Any]]:
        return self._list_items(self._api_url("/tables"), page_size=100)

    def create_table(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json("POST", self._api_url("/tables"), json=payload)
        return self._unwrap(data, "table")

    def delete_table(self, table_id: str) -> None:
        self._request_json("DELETE", self._api_url(f"/tables/{table_id}"))

    def list_fields(self, table_id: str) -> list[dict[str, Any]]:
        return self._list_items(self._api_url(f"/tables/{table_id}/fields"), page_size=100)

    def create_field(self, table_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json("POST", self._api_url(f"/tables/{table_id}/fields"), json=payload)
        return self._unwrap(data, "field")

    def update_field(self, table_id: str, field_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json("PUT", self._api_url(f"/tables/{table_id}/fields/{field_id}"), json=payload)
        return self._unwrap(data, "field")

    def list_views(self, table_id: str) -> list[dict[str, Any]]:
        return self._list_items(self._api_url(f"/tables/{table_id}/views"), page_size=100)

    def get_view(self, table_id: str, view_id: str) -> dict[str, Any]:
        data = self._request_json("GET", self._api_url(f"/tables/{table_id}/views/{view_id}"))
        return self._unwrap(data, "view")

    def create_view(self, table_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json("POST", self._api_url(f"/tables/{table_id}/views"), json=payload)
        return self._unwrap(data, "view")

    def update_view(self, table_id: str, view_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json("PATCH", self._api_url(f"/tables/{table_id}/views/{view_id}"), json=payload)
        return self._unwrap(data, "view")

    def delete_view(self, table_id: str, view_id: str) -> None:
        self._request_json("DELETE", self._api_url(f"/tables/{table_id}/views/{view_id}"))

    def _api_url(self, suffix: str) -> str:
        if not self.config.app_token:
            raise FeishuApiError("Feishu Base URL is not configured")
        return f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.config.app_token}{suffix}"

    def _list_items(self, url: str, *, page_size: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = self._request_json("GET", url, params=params)
            items.extend(item for item in data.get("items", []) if isinstance(item, dict))
            if not data.get("has_more"):
                return items
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise FeishuApiError("Feishu pagination response is missing page_token")

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        token = self._tenant_access_token()
        if not token:
            raise FeishuApiError("Feishu credentials are not configured")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        call = {
            "GET": self.get,
            "POST": self.post,
            "PUT": self.put,
            "PATCH": self.patch,
            "DELETE": self.delete,
        }[method]
        last_error: FeishuApiError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = call(url, headers=headers, timeout=30, **kwargs)
                response.raise_for_status()
                payload = response.json()
                code = payload.get("code")
                if code not in (0, None):
                    numeric_code = int(code) if isinstance(code, (int, str)) and str(code).isdigit() else None
                    message = str(payload.get("msg") or "Feishu API request failed")
                    raise FeishuApiError(
                        f"Feishu API error {numeric_code}: {message}",
                        code=numeric_code,
                        retryable=numeric_code in RETRYABLE_CODES,
                    )
                data = payload.get("data") or {}
                if not isinstance(data, dict):
                    raise FeishuApiError("Feishu API returned an invalid data object")
                return data
            except FeishuApiError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_retries:
                    raise
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                retryable = status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
                last_error = FeishuApiError(
                    f"Feishu HTTP request failed{f' ({status_code})' if status_code else ''}",
                    retryable=retryable,
                )
                if not retryable or attempt >= self.max_retries:
                    raise last_error from exc
            self.sleep(0.25 * (2**attempt))
        raise last_error or FeishuApiError("Feishu API request failed")

    @staticmethod
    def _unwrap(data: dict[str, Any], key: str) -> dict[str, Any]:
        nested = data.get(key)
        return nested if isinstance(nested, dict) else data

    def batch_create_records(self, records: list[dict[str, Any]]) -> FeishuResult:
        if not records:
            return FeishuResult(sent=False, error="no records to send")
        token = self._tenant_access_token()
        if not (self.config.app_token and self.config.table_id and token):
            return FeishuResult(sent=False, error="feishu credentials are not configured")

        url = (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.config.app_token}/tables/{self.config.table_id}/records/batch_create"
        )
        record_ids = []
        for i in range(0, len(records), 500):
            batch = records[i : i + 500]
            response = self.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": batch},
                timeout=30,
            )
            res = self._records_result(response)
            if not res.sent:
                return res
            record_ids.extend(res.record_ids)
        return FeishuResult(sent=True, record_ids=record_ids)

    def batch_update_records(self, records: list[dict[str, Any]]) -> FeishuResult:
        if not records:
            return FeishuResult(sent=False, error="no records to send")
        token = self._tenant_access_token()
        if not (self.config.app_token and self.config.table_id and token):
            return FeishuResult(sent=False, error="feishu credentials are not configured")

        url = (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.config.app_token}/tables/{self.config.table_id}/records/batch_update"
        )
        for i in range(0, len(records), 500):
            batch = records[i : i + 500]
            response = self.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": batch},
                timeout=30,
            )
            res = self._records_result(response)
            if not res.sent:
                return res
        return FeishuResult(sent=True)

    def _tenant_access_token(self) -> str:
        if self.config.tenant_access_token:
            return self.config.tenant_access_token
        if not (self.config.app_id and self.config.app_secret):
            return ""
        response = self.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (0, None):
            return ""
        return str(payload.get("tenant_access_token") or "")

    @staticmethod
    def _records_result(response: Any) -> FeishuResult:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            body = getattr(response, "text", "") or ""
            return FeishuResult(sent=False, error=f"{exc}; {body}".strip())
        payload = response.json()
        if payload.get("code") not in (0, None):
            return FeishuResult(sent=False, error=str(payload))
        record_ids = [record.get("record_id", "") for record in payload.get("data", {}).get("records", [])]
        return FeishuResult(sent=True, record_ids=[record_id for record_id in record_ids if record_id])

    def list_all_records(self, table_id: str | None = None) -> list[dict[str, Any]]:
        token = self._tenant_access_token()
        target_table_id = table_id or self.config.table_id
        if not (self.config.app_token and target_table_id and token):
            raise ValueError("feishu credentials are not configured")

        url = (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.config.app_token}/tables/{target_table_id}/records"
        )
        records = []
        page_token = None
        has_more = True
        while has_more:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token

            response = self.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, None):
                raise ValueError(f"Feishu API error: {payload}")

            data = payload.get("data", {})
            records.extend(data.get("items", []))
            has_more = data.get("has_more", False)
            page_token = data.get("page_token")
        return records


class FeishuBot:
    def __init__(self, webhook_url: str, post: Callable[..., Any] | None = None):
        self.webhook_url = webhook_url
        self.post = post or requests.post

    def send_text(self, text: str) -> FeishuResult:
        if not self.webhook_url:
            return FeishuResult(sent=False, error="feishu webhook is not configured")
        response = self.post(self.webhook_url, json={"msg_type": "text", "content": {"text": text}}, timeout=20)
        response.raise_for_status()
        return FeishuResult(sent=True)

