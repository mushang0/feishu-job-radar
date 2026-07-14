from jobpicky.feishu_records import build_create_fields, build_update_fields


def _row(**overrides):
    row = {
        "job_id": 42,
        "title": "FPGA工程师",
        "company": "示例公司",
        "city": "上海",
        "target_graduate_year": "2027届",
        "batch": "秋招",
        "recommend_reason": "命中岗位方向",
        "official_url": "https://careers.example.com/job/42",
        "apply_url": None,
        "original_url": "https://source.example.com/job/42",
        "deadline": "2026-08-01",
        "first_seen": "2026-07-11T09:30:00",
        "last_seen": "2026-07-11T10:30:00",
        "recommendation_active": True,
        "user_status": None,
        "next_action": None,
        "note": "",
    }
    row.update(overrides)
    return row


def test_new_record_uses_managed_schema_and_defaults_to_pending():
    fields = build_create_fields(_row())

    assert fields["公司"] == "示例公司"
    assert fields["岗位"] == "FPGA工程师"
    assert fields["求职状态"] == "待处理"
    assert fields["投递入口"] == {"link": "https://careers.example.com/job/42", "text": "打开投递入口"}
    assert isinstance(fields["截止时间"], int)
    assert fields["当前推荐"] is True
    assert set(fields) == {"公司", "岗位", "当前推荐", "城市", "届别", "批次", "投递入口", "截止时间", "求职状态"}


def test_recreated_tracked_record_restores_known_local_user_fields():
    fields = build_create_fields(_row(user_status="面试中", next_action="7月15日二面", note="准备项目介绍"))

    assert fields["求职状态"] == "面试中"
    assert fields["备注"] == "准备项目介绍"


def test_update_only_contains_synced_user_visible_fields():
    fields = build_update_fields(_row(user_status="收藏", next_action="面试", note="keep", recommendation_active=False))

    assert {"求职状态", "备注"}.isdisjoint(fields)
    assert fields["当前推荐"] is False
    assert set(fields) == {"公司", "岗位", "当前推荐", "城市", "届别", "批次", "投递入口", "截止时间"}
