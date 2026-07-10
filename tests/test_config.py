from pathlib import Path

from job_monitor.config import load_config


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
