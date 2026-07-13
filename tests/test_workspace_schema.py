from jobpicky.workspace_schema import WORKSPACE_SCHEMA_VERSION, desired_workspace


def test_desired_workspace_uses_company_as_primary_field_and_declares_user_views():
    workspace = desired_workspace()

    assert WORKSPACE_SCHEMA_VERSION == "2"
    assert workspace.primary_field == "公司"
    assert workspace.field_names == (
        "公司",
        "岗位",
        "城市",
        "届别",
        "批次",
        "投递入口",
        "截止时间",
        "求职状态",
        "备注",
    )
    assert {view.name for view in workspace.views} == {"待处理", "收藏", "投递进度"}


def test_workspace_schema_has_exact_user_status_options_and_types():
    workspace = desired_workspace()
    status = workspace.field("求职状态")

    assert status.type_code == 3
    assert status.property == {
        "options": [
            {"name": "待处理"},
            {"name": "收藏"},
            {"name": "不合适"},
            {"name": "已投递"},
            {"name": "笔试中"},
            {"name": "面试中"},
            {"name": "Offer"},
            {"name": "已结束"},
        ]
    }
    assert workspace.field("截止时间").type_code == 5
    assert workspace.field("投递入口").type_code == 15


def test_table_create_payload_is_utf8_safe_and_uses_company_as_primary_field():
    payload = desired_workspace().table_create_payload()

    assert payload["table"]["name"] == "求职工作台"
    assert payload["table"]["default_view_name"] == "待处理"
    assert payload["table"]["fields"][0] == {"field_name": "公司", "type": 1}
    assert next(field for field in payload["table"]["fields"] if field["field_name"] == "求职状态")["property"]["options"][0]["name"] == "待处理"


def test_workspace_views_define_types_filters_and_visible_fields():
    views = {view.name: view for view in desired_workspace().views}

    assert views["待处理"].view_type == "grid"
    assert views["待处理"].status_values == ("待处理",)
    assert views["收藏"].status_values == ("收藏",)
    assert views["收藏"].view_type == "gallery"
    assert views["投递进度"].view_type == "kanban"
    assert views["投递进度"].status_values == ()
    assert views["投递进度"].excluded_status_values == ("不合适",)
