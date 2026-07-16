from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any


@lru_cache(maxsize=1)
def job_taxonomy() -> dict[str, Any]:
    resource = files("jobpicky.resources").joinpath("job_taxonomy_v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def role_sections() -> tuple[dict[str, Any], ...]:
    sections: list[dict[str, Any]] = []
    for section in job_taxonomy()["sections"]:
        options = []
        for direction in section["directions"]:
            search_terms = list(dict.fromkeys([
                direction["label"],
                *direction.get("aliases", []),
                *direction.get("terms", []),
                *direction.get("weak_terms", []),
            ]))
            options.append({
                "value": direction["id"],
                "label": direction["label"],
                "search_terms": search_terms,
            })
        sections.append({"id": section["id"], "label": section["label"], "options": tuple(options)})
    return tuple(sections)


def role_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for section in job_taxonomy()["sections"]:
        for direction in section["directions"]:
            groups[direction["id"]] = list(dict.fromkeys([
                *direction.get("terms", []),
                *direction.get("weak_terms", []),
            ]))
    return groups


def role_labels() -> dict[str, str]:
    return {
        direction["id"]: direction["label"]
        for section in job_taxonomy()["sections"]
        for direction in section["directions"]
    }


def role_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for section in job_taxonomy()["sections"]:
        for direction in section["directions"]:
            for value in [direction["id"], direction["label"], *direction.get("aliases", [])]:
                aliases[str(value).strip().lower()] = direction["id"]
    legacy = {
        "硬件/嵌入式": "hardware.embedded",
        "硬件": "hardware.circuit",
        "嵌入式": "hardware.embedded",
        "半导体/芯片": "chip.digital",
        "芯片验证/eda": "chip.verification",
        "测试/验证": "software.test",
        "ai/大模型/推理部署": "ai.inference",
        "算法/研发": "ai.algorithm",
        "数据/数据分析": "data.analysis",
        "客户端": "software.client",
        "云计算/devops": "cloud.devops",
        "网络/安全": "security.cyber",
        "电气/电力电子": "electrical.power",
        "机械": "mechanical.design",
        "工艺/制造": "manufacturing.process",
        "产品": "product.manager",
        "设计": "design.uiux",
        "医药": "medicine.rnd",
        "法务": "legal",
        "财务": "finance",
    }
    aliases.update({key.lower(): value for key, value in legacy.items()})
    return aliases


def canonical_role_id(value: str) -> str:
    text = str(value or "").strip()
    return role_aliases().get(text.lower(), text)
