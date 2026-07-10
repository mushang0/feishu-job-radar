from __future__ import annotations

import getpass
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedBaseUrl:
    origin: str
    app_token: str


@dataclass(frozen=True, slots=True)
class InitializationPreview:
    base_url: str
    table_name: str
    pending_candidates: int

    def render(self) -> str:
        return (
            "首次初始化预览\n"
            f"- 目标多维表格：{self.base_url}\n"
            f"- 创建或修复数据表：{self.table_name}\n"
            f"- 当前待同步候选：{self.pending_candidates} 条"
        )


def parse_base_url(value: str) -> ParsedBaseUrl:
    parsed = urlparse(str(value).strip())
    if parsed.scheme != "https":
        raise ConfigError("飞书多维表格链接必须使用 HTTPS")
    host = (parsed.hostname or "").lower()
    if host != "feishu.cn" and not host.endswith(".feishu.cn"):
        raise ConfigError("请输入 feishu.cn 域名下的多维表格链接")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] == "wiki":
        raise ConfigError("当前版本仅支持 /base/ 链接，请先在飞书中打开原始 Base 链接")
    if len(parts) != 2 or parts[0] != "base" or not parts[1]:
        raise ConfigError("链接中缺少可识别的 Base App Token")
    return ParsedBaseUrl(origin=f"https://{parsed.netloc}", app_token=parts[1])


def collect_missing_config(
    config: dict,
    *,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
    output_fn: Callable[[str], None] = print,
) -> dict:
    collected = deepcopy(config)
    profile = collected.setdefault("user_profile", {})
    feishu = collected.setdefault("feishu", {})
    output_fn("请完成首次使用配置。逗号分隔的项目可填写多个值。")

    prompts = (
        ("graduate_years", "毕业届别（例如 2027届）：", True),
        ("batches", "招聘批次（例如 秋招,实习）：", True),
        ("role_groups", "岗位方向（例如 硬件/嵌入式）：", True),
        ("target_cities", "目标城市（可留空）：", False),
        ("must_watch_companies", "重点公司（可留空）：", False),
    )
    for key, prompt, required in prompts:
        if key in profile and (profile.get(key) or not required):
            continue
        values = _split_values(input_fn(prompt))
        if required and not values:
            raise ConfigError(f"{prompt.split('（')[0]}不能为空")
        profile[key] = values

    if not feishu.get("base_url"):
        feishu["base_url"] = input_fn("飞书多维表格 Base 链接：").strip()
    parse_base_url(feishu["base_url"])
    if not feishu.get("app_id"):
        feishu["app_id"] = input_fn("飞书 App ID：").strip()
    if not feishu.get("app_secret"):
        feishu["app_secret"] = secret_input_fn("飞书 App Secret（输入不会显示）：").strip()
    return collected


def confirm_initialization(
    preview: InitializationPreview,
    *,
    assume_yes: bool,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> bool:
    output_fn(preview.render())
    if assume_yes:
        return True
    answer = input_fn("确认开始创建工作台、扫描和同步？[y/N]：").strip().lower()
    return answer in {"y", "yes", "是"}


def _split_values(value: str) -> list[str]:
    normalized = str(value).replace("，", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]
