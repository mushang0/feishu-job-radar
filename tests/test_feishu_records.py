from job_monitor.feishu_records import build_create_fields, build_update_fields, index_remote_records


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

    assert fields["岗位"] == "FPGA工程师"
    assert fields["岗位ID"] == "42"
    assert fields["求职状态"] == "待处理"
    assert fields["推荐有效"] is True
    assert fields["投递入口"] == {"link": "https://careers.example.com/job/42", "text": "打开投递入口"}
    assert fields["来源详情"] == {"link": "https://source.example.com/job/42", "text": "查看来源"}
    assert isinstance(fields["截止时间"], int)
    assert "用户状态" not in fields


def test_recreated_tracked_record_restores_known_local_user_fields():
    fields = build_create_fields(_row(user_status="面试中", next_action="7月15日二面", note="准备项目介绍"))

    assert fields["求职状态"] == "面试中"
    assert fields["下次行动"] == "7月15日二面"
    assert fields["备注"] == "准备项目介绍"


def test_update_never_contains_user_managed_fields():
    fields = build_update_fields(_row(user_status="收藏", next_action="面试", note="keep", recommendation_active=False))

    assert {"求职状态", "下次行动", "备注"}.isdisjoint(fields)
    assert fields["推荐有效"] is False


def test_remote_index_matches_by_job_id_and_reports_duplicates_and_invalid_rows():
    index = index_remote_records(
        [
            {"record_id": "rec-1", "fields": {"岗位ID": "42"}},
            {"record_id": "rec-2", "fields": {"岗位ID": [{"text": "42"}]}},
            {"record_id": "rec-invalid", "fields": {"岗位ID": "not-a-number"}},
            {"record_id": "rec-blank", "fields": {}},
        ]
    )

    assert index.by_job_id == {}
    assert index.duplicate_job_ids == frozenset({42})
    assert index.invalid_record_ids == ("rec-invalid", "rec-blank")


def test_remote_index_keeps_unique_job_ids():
    index = index_remote_records(
        [
            {"record_id": "rec-1", "fields": {"岗位ID": "1"}},
            {"record_id": "rec-2", "fields": {"岗位ID": "2"}},
        ]
    )

    assert index.by_job_id == {1: "rec-1", 2: "rec-2"}
    assert not index.duplicate_job_ids
