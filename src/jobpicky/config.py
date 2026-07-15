from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ONBOARDING_BATCH_OPTIONS = ("校招", "实习")
LEGACY_DEFAULT_EXCLUDED_ROLES = ("销售", "市场", "运营", "HR", "财务")

ONBOARDING_ROLE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "label": "硬件与芯片",
        "options": (
            {"value": "嵌入式", "label": "嵌入式"},
            {"value": "硬件", "label": "硬件"},
            {"value": "FPGA", "label": "FPGA"},
            {"value": "电气/电力电子", "label": "电气/电力电子"},
            {"value": "半导体/芯片", "label": "芯片/半导体"},
            {"value": "芯片验证/EDA", "label": "芯片验证/EDA"},
            {"value": "测试/验证", "label": "测试/验证"},
        ),
    },
    {
        "label": "算法与数据",
        "options": (
            {"value": "算法", "label": "算法"},
            {"value": "机器学习/深度学习", "label": "机器学习/深度学习"},
            {"value": "AI/大模型/推理部署", "label": "AI/大模型"},
            {"value": "数据/数据分析", "label": "数据/数据分析"},
            {"value": "具身智能/机器人", "label": "机器人/具身智能"},
        ),
    },
    {
        "label": "软件与平台",
        "options": (
            {"value": "后端开发", "label": "后端开发"},
            {"value": "前端开发", "label": "前端开发"},
            {"value": "客户端", "label": "客户端"},
            {"value": "云计算/DevOps", "label": "云计算/DevOps"},
            {"value": "网络/安全", "label": "网络/安全"},
        ),
    },
    {
        "label": "工程与职能",
        "options": (
            {"value": "机械", "label": "机械/结构"},
            {"value": "材料", "label": "材料"},
            {"value": "工艺/制造", "label": "工艺/制造"},
            {"value": "产品", "label": "产品"},
            {"value": "设计", "label": "设计"},
            {"value": "医药", "label": "医药/生物"},
        ),
    },
)


DEFAULT_CONFIG: dict[str, Any] = {
    "profile": {"name": "default", "version": 2},
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
        "graduate_years": [],
        "batches": list(ONBOARDING_BATCH_OPTIONS),
        "role_groups": ["硬件/嵌入式", "半导体/芯片"],
        "target_industries": [],
        "target_cities": [],
        "custom_keywords": [],
        "must_watch_companies": [],
        "exclude_role_groups": [],
        "recall_mode": "balanced",
        "daily_push_limit": 20,
    },
    "system_taxonomy": {
        "role_groups": {
            "嵌入式": [
                "嵌入式", "单片机", "MCU", "BSP", "固件", "驱动开发", "驱动工程师",
                "RTOS", "FreeRTOS", "Zephyr", "C语言", "C++",
            ],
            "硬件": [
                "硬件", "原理图", "电路设计", "数字电路", "模拟电路", "PCB", "射频",
                "信号完整性", "电源设计", "硬件工程师",
            ],
            "FPGA": ["FPGA", "Verilog", "VHDL", "RTL", "Vivado", "Quartus", "时序分析"],
            "电气/电力电子": [
                "电气", "电气工程", "电力电子", "电机控制", "PLC", "变频器", "高压", "低压",
                "配电", "自动化控制",
            ],
            "硬件/嵌入式": ["硬件", "嵌入式", "单片机", "驱动开发", "数字电路", "模拟电路", "PCB", "Verilog", "FPGA"],
            "半导体/芯片": ["半导体", "芯片", "IC", "芯片验证", "版图", "封装", "测试开发"],
            "芯片验证/EDA": [
                "芯片验证", "IC验证", "验证工程师", "EDA", "ASIC", "SoC", "UVM", "SystemVerilog",
                "形式验证", "数字后端", "版图设计",
            ],
            "测试/验证": ["测试开发", "测试工程师", "软件测试", "自动化测试", "功能测试", "验证工程师", "质量工程"],
            "算法": ["算法", "算法工程师", "推荐", "搜索", "排序", "优化算法", "研发工程师"],
            "机器学习/深度学习": [
                "机器学习", "深度学习", "计算机视觉", "CV", "NLP", "自然语言处理", "强化学习",
                "模型训练", "特征工程",
            ],
            "算法/研发": ["算法", "机器学习", "深度学习", "计算机视觉", "NLP", "研发工程师"],
            "AI/大模型/推理部署": [
                "大模型", "LLM", "生成式AI", "AIGC", "推理", "推理优化", "模型部署",
                "端侧部署", "模型压缩", "量化", "蒸馏", "TensorRT", "ONNX", "vLLM",
            ],
            "具身智能/机器人": [
                "具身智能", "机器人", "机械臂", "运动控制", "导航算法", "SLAM", "路径规划",
                "强化学习", "感知算法", "多模态",
            ],
            "数据/数据分析": ["数据分析", "数据科学", "数据挖掘", "商业分析", "数仓", "ETL", "SQL", "BI"],
            "后端开发": ["后端开发", "服务端", "Java", "Go", "Python", "C++", "微服务", "API", "数据库"],
            "前端开发": ["前端开发", "前端工程师", "JavaScript", "TypeScript", "React", "Vue", "Web"],
            "客户端": ["客户端", "移动端", "Android", "iOS", "Flutter", "鸿蒙", "桌面开发"],
            "云计算/DevOps": [
                "云计算", "DevOps", "MLOps", "SRE", "Kubernetes", "Docker", "云原生", "CI/CD", "推理服务",
            ],
            "网络/安全": ["网络", "网络安全", "信息安全", "安全工程师", "渗透测试", "密码学", "通信工程"],
            "开发/部署": ["部署", "MLOps", "DevOps", "云原生", "Kubernetes", "Docker", "推理服务"],
            "互联网/技术": ["互联网", "软件开发", "后端开发", "前端开发", "客户端开发", "云计算"],
            "产品": ["产品经理", "产品运营"],
            "机械": ["机械", "结构", "CAE", "工艺"],
            "材料": ["材料", "高分子", "金属", "电池材料"],
            "工艺/制造": ["工艺", "制造", "生产工艺", "制程", "质量管理", "自动化产线", "精益生产"],
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
        "role_input_aliases": {
            "嵌入式开发": "嵌入式",
            "电气": "电气/电力电子",
            "电力电子": "电气/电力电子",
            "芯片验证": "芯片验证/EDA",
            "测试": "测试/验证",
            "机器学习": "机器学习/深度学习",
            "深度学习": "机器学习/深度学习",
            "后端": "后端开发",
            "前端": "前端开发",
            "客户端开发": "客户端",
            "云计算": "云计算/DevOps",
            "网络安全": "网络/安全",
            "推理部署": "AI/大模型/推理部署",
            "大模型": "AI/大模型/推理部署",
            "推理优化": "AI/大模型/推理部署",
            "端侧部署": "AI/大模型/推理部署",
            "ai推理": "AI/大模型/推理部署",
            "ai": "AI/大模型/推理部署",
            "具身智能": "具身智能/机器人",
            "机器人": "具身智能/机器人",
            "部署": "开发/部署",
            "互联网": "互联网/技术",
        },
        "company_groups": {
            "互联网大厂": ["腾讯", "字节跳动", "阿里巴巴", "百度", "美团", "京东", "网易", "快手", "小米", "大疆"],
        },
        "company_aliases": {
            "腾讯": ["腾讯科技", "腾讯云"],
            "字节跳动": ["字节", "抖音"],
            "阿里巴巴": ["阿里", "淘宝", "蚂蚁集团"],
            "百度": ["百度在线"],
            "美团": ["北京三快", "美团点评"],
            "京东": ["京东科技", "京东集团"],
            "网易": ["网易杭州", "网易互娱"],
            "快手": ["北京快手"],
            "小米": ["小米科技"],
            "大疆": ["DJI", "大疆创新", "深圳市大疆创新科技有限公司"],
        },
    },
    "feishu": {
        "base_url": "",
        "workspace_table_id": "",
        "workspace_schema_version": "",
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


def validate_config(
    config: dict[str, Any],
    *,
    require_feishu: bool = False,
    require_graduate_years: bool = True,
    require_batches: bool = False,
) -> list[str]:
    profile = config.get("user_profile", {})
    errors: list[str] = []
    if require_graduate_years and not profile.get("graduate_years"):
        errors.append("至少选择一个毕业届别")
    if require_batches and not profile.get("batches"):
        errors.append("至少选择一个招聘类型")
    if not profile.get("role_groups"):
        errors.append("至少选择一个岗位方向")
    if require_feishu:
        feishu = config.get("feishu", {})
        if not feishu.get("base_url"):
            errors.append("请填写飞书多维表格 Base 链接")
        if not feishu.get("app_id"):
            errors.append("请填写飞书 App ID")
        if not feishu.get("app_secret"):
            errors.append("请填写飞书 App Secret")
    return errors


def save_config(config: dict[str, Any], path: str | Path = "config.yaml") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_config = _config_for_storage(config)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(safe_config, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _config_for_storage(config: dict[str, Any]) -> dict[str, Any]:
    profile_keys = (
        "graduate_years",
        "batches",
        "role_groups",
        "target_industries",
        "target_cities",
        "custom_keywords",
        "must_watch_companies",
        "exclude_role_groups",
        "recall_mode",
        "daily_push_limit",
    )
    feishu_keys = (
        "base_url",
        "bitable_app_token",
        "app_id",
        "app_secret",
        "webhook_url",
        "workspace_table_id",
        "workspace_schema_version",
    )
    stored: dict[str, Any] = {
        "user_profile": {
            key: deepcopy(config.get("user_profile", {}).get(key, DEFAULT_CONFIG["user_profile"].get(key)))
            for key in profile_keys
        },
        "feishu": {
            key: deepcopy(config.get("feishu", {}).get(key, ""))
            for key in feishu_keys
            if config.get("feishu", {}).get(key, "") not in (None, "") or key in {"base_url", "app_id", "app_secret", "webhook_url"}
        },
    }
    for key, value in config.items():
        if key in {"user_profile", "feishu"}:
            continue
        if key not in DEFAULT_CONFIG:
            stored[key] = deepcopy(value)
            continue
        difference = _deep_diff(value, DEFAULT_CONFIG[key])
        if difference not in (None, {}, []):
            stored[key] = difference
    return stored


def _deep_diff(value: Any, default: Any) -> Any:
    if isinstance(value, dict) and isinstance(default, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key not in default:
                result[key] = deepcopy(child)
                continue
            difference = _deep_diff(child, default[key])
            if difference not in (None, {}, []):
                result[key] = difference
        return result
    return None if value == default else deepcopy(value)

