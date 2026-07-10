from pathlib import Path

import pytest
import yaml

from job_monitor.onboarding import (
    ConfigError,
    InitializationPreview,
    collect_missing_config,
    confirm_initialization,
    parse_base_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.feishu.cn/base/bascnToken",
        "https://example.feishu.cn/base/bascnToken?table=tblOld&view=vewOld",
    ],
)
def test_parse_base_url_extracts_app_token_and_origin(url):
    parsed = parse_base_url(url)

    assert parsed.app_token == "bascnToken"
    assert parsed.origin == "https://example.feishu.cn"


@pytest.mark.parametrize(
    "url,message",
    [
        ("https://example.feishu.cn/wiki/wikcnToken", "base"),
        ("http://example.feishu.cn/base/bascnToken", "HTTPS"),
        ("https://example.com/base/bascnToken", "feishu.cn"),
        ("https://example.feishu.cn/base/", "App Token"),
    ],
)
def test_parse_base_url_rejects_unsupported_or_unsafe_urls(url, message):
    with pytest.raises(ConfigError, match=message):
        parse_base_url(url)


def test_collect_missing_config_prompts_only_for_required_inputs():
    answers = iter(
        [
            "2027届",
            "秋招,实习",
            "硬件/嵌入式",
            "上海,深圳",
            "",
            "https://example.feishu.cn/base/bascnToken",
            "cli-app",
        ]
    )
    secrets = []

    config = collect_missing_config(
        {"user_profile": {}, "feishu": {}},
        input_fn=lambda _: next(answers),
        secret_input_fn=lambda _: secrets.append("asked") or "app-secret",
        output_fn=lambda _: None,
    )

    assert config["user_profile"]["graduate_years"] == ["2027届"]
    assert config["user_profile"]["batches"] == ["秋招", "实习"]
    assert config["user_profile"]["role_groups"] == ["硬件/嵌入式"]
    assert config["user_profile"]["target_cities"] == ["上海", "深圳"]
    assert config["feishu"]["base_url"].endswith("bascnToken")
    assert config["feishu"]["app_id"] == "cli-app"
    assert config["feishu"]["app_secret"] == "app-secret"
    assert secrets == ["asked"]


def test_confirm_initialization_requires_explicit_yes_unless_flag_is_set():
    preview = InitializationPreview(base_url="https://example.feishu.cn/base/token", table_name="求职工作台", pending_candidates=12)

    assert confirm_initialization(preview, assume_yes=False, input_fn=lambda _: "no", output_fn=lambda _: None) is False
    assert confirm_initialization(preview, assume_yes=False, input_fn=lambda _: "是", output_fn=lambda _: None) is True
    assert confirm_initialization(preview, assume_yes=True, input_fn=lambda _: pytest.fail("must not prompt"), output_fn=lambda _: None) is True


def test_preview_redacts_credentials():
    preview = InitializationPreview(base_url="https://example.feishu.cn/base/token", table_name="求职工作台", pending_candidates=3)

    text = preview.render()

    assert "求职工作台" in text
    assert "3" in text
    assert "secret" not in text.lower()
