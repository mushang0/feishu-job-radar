from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "profile": {"name": "default", "version": 1},
    "crawler": {
        "source": "wondercv",
        "start_date": "2026-06-15",
        "max_pages_init": 50,
        "max_pages_daily": 20,
        "recent_update_days": 7,
        "min_interval_seconds": 2,
        "max_interval_seconds": 5,
    },
    "user_profile": {
        "graduate_years": ["2027届"],
        "batches": ["秋招", "提前批", "实习"],
        "role_groups": ["硬件/嵌入式", "半导体/芯片"],
        "target_industries": [],
        "target_cities": [],
        "must_watch_companies": [],
        "exclude_role_groups": ["销售", "市场", "运营", "HR", "财务"],
        "recall_mode": "balanced",
        "daily_push_limit": 20,
    },
    "system_taxonomy": {
        "role_groups": {
            "硬件/嵌入式": ["硬件", "嵌入式", "单片机", "驱动开发", "数字电路", "模拟电路", "PCB", "Verilog", "FPGA"],
            "半导体/芯片": ["半导体", "芯片", "IC", "芯片验证", "版图", "封装", "测试开发"],
            "算法/研发": ["算法", "机器学习", "深度学习", "计算机视觉", "NLP", "研发工程师"],
            "产品": ["产品经理", "产品运营"],
            "机械": ["机械", "结构", "CAE", "工艺"],
            "材料": ["材料", "高分子", "金属", "电池材料"],
            "医药": ["医药", "临床", "药物", "生物"],
            "法务": ["法务", "合规", "知识产权"],
            "设计": ["设计", "视觉", "交互", "UI", "UX"],
            "财务": ["财务", "会计", "审计", "税务"],
        },
        "exclude_role_groups": {
            "销售": ["销售", "客户经理", "商务拓展", "BD"],
            "市场": ["市场", "营销", "品牌", "公关"],
            "运营": ["运营", "内容运营", "用户运营"],
            "HR": ["HR", "人力资源", "招聘专员"],
            "财务": ["财务", "会计", "审计"],
        },
        "generic_role_terms": ["研发类", "技术类", "工程师类", "校招生", "管培生", "研究员", "技术培训生"],
        "important_company_types": ["上市公司", "央企", "国企", "外企", "事业单位"],
        "important_company_marks": ["知名大厂", "研究院", "有内推"],
        "company_aliases": {},
    },
    "feishu": {
        "bitable_app_token": "",
        "table_id": "",
        "tenant_access_token": "",
        "app_id": "",
        "app_secret": "",
        "webhook_url": "",
    },
}


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path)
    if config_path.exists():
        user_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        _deep_merge(config, user_config)
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

