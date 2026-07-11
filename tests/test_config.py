from pathlib import Path

import yaml

from job_monitor.config import load_config, save_config


def test_load_config_merges_user_yaml_with_defaults(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
crawler:
  max_pages_daily: 3
user_profile:
  role_groups:
    - 硬件/嵌入式
feishu:
  webhook_url: https://example.com/hook
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["crawler"]["max_pages_daily"] == 3
    assert config["crawler"]["source"] == "wondercv"
    assert config["user_profile"]["role_groups"] == ["硬件/嵌入式"]
    assert config["user_profile"]["daily_push_limit"] == 20
    assert "matching" not in config
    assert "keywords" not in config
    assert config["feishu"]["webhook_url"] == "https://example.com/hook"


def test_validate_config_reports_missing_required_user_inputs():
    from job_monitor.config import validate_config

    errors = validate_config({"user_profile": {}, "feishu": {}})

    assert "至少选择一个毕业届别" in errors
    assert "至少选择一个岗位方向" in errors


def test_validate_config_can_require_first_run_feishu_inputs():
    from job_monitor.config import validate_config

    errors = validate_config(
        {"user_profile": {"graduate_years": ["2027届"], "role_groups": ["硬件/嵌入式"]}, "feishu": {}},
        require_feishu=True,
    )

    assert "请填写飞书多维表格 Base 链接" in errors
    assert "请填写飞书 App ID" in errors
    assert "请填写飞书 App Secret" in errors


def test_save_config_is_utf8_atomic_and_drops_tenant_token(tmp_path: Path):
    path = tmp_path / "config.yaml"
    save_config(
        {
            "user_profile": {"role_groups": ["硬件/嵌入式"]},
            "feishu": {"app_secret": "keep-locally", "bitable_app_token": "app-token", "tenant_access_token": "temporary-token"},
        },
        path,
    )

    text = path.read_text(encoding="utf-8")
    saved = yaml.safe_load(text)
    assert "硬件/嵌入式" in text
    assert saved["feishu"]["app_secret"] == "keep-locally"
    assert saved["feishu"]["bitable_app_token"] == "app-token"
    assert "tenant_access_token" not in saved["feishu"]
    assert list(tmp_path.glob("*.tmp")) == []
