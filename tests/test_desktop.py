from job_monitor.desktop import apply_form_values


def test_desktop_form_saves_profile_and_keeps_existing_secret():
    config = {"user_profile": {}, "feishu": {"app_secret": "existing-secret"}}

    result = apply_form_values(config, {
        "graduate_years": "2027届", "batches": "秋招, 实习", "role_groups": "硬件/嵌入式",
        "target_cities": "上海", "must_watch_companies": "", "base_url": "https://example.feishu.cn/base/token",
        "app_id": "cli-app", "app_secret": "",
    })

    assert result["user_profile"]["batches"] == ["秋招", "实习"]
    assert result["feishu"]["app_secret"] == "existing-secret"


def test_desktop_form_requires_core_preferences_and_credentials():
    config = {"user_profile": {}, "feishu": {}}

    try:
        apply_form_values(config, {"base_url": "https://example.feishu.cn/base/token"})
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("missing desktop form fields must be rejected")
