from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import requests


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    app_token: str = ""
    table_id: str = ""
    tenant_access_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FeishuConfig":
        feishu = config.get("feishu", {})
        return cls(
            app_token=feishu.get("bitable_app_token", ""),
            table_id=feishu.get("table_id", ""),
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
    ):
        self.config = config
        self.post = post or requests.post
        self.get = get or requests.get


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

    def list_all_records(self) -> list[dict[str, Any]]:
        token = self._tenant_access_token()
        if not (self.config.app_token and self.config.table_id and token):
            raise ValueError("feishu credentials are not configured")

        url = (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.config.app_token}/tables/{self.config.table_id}/records"
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

