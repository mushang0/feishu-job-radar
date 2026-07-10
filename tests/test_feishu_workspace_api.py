from unittest.mock import Mock

import pytest

from job_monitor.feishu import FeishuApiError, FeishuBitableClient, FeishuConfig


def _response(payload, *, status_code=200, text=""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _config() -> FeishuConfig:
    return FeishuConfig(app_token="base-token", table_id="table-id", tenant_access_token="tenant-token")


def test_client_lists_all_tables_with_pagination():
    get = Mock(
        side_effect=[
            _response(
                {
                    "code": 0,
                    "data": {
                        "items": [{"table_id": "tbl-1", "name": "现有表"}],
                        "has_more": True,
                        "page_token": "next-token",
                    },
                }
            ),
            _response(
                {
                    "code": 0,
                    "data": {
                        "items": [{"table_id": "tbl-2", "name": "求职工作台"}],
                        "has_more": False,
                    },
                }
            ),
        ]
    )

    tables = FeishuBitableClient(_config(), get=get).list_tables()

    assert [table["table_id"] for table in tables] == ["tbl-1", "tbl-2"]
    assert get.call_args_list[1].kwargs["params"]["page_token"] == "next-token"


def test_client_creates_table_with_unmodified_chinese_payload():
    post = Mock(
        return_value=_response(
            {
                "code": 0,
                "data": {"table_id": "tbl-new", "default_view_id": "vew-default", "field_id_list": ["fld-primary"]},
            }
        )
    )
    client = FeishuBitableClient(_config(), post=post)

    created = client.create_table({"table": {"name": "求职工作台", "default_view_name": "待处理"}})

    assert created["table_id"] == "tbl-new"
    assert post.call_args.kwargs["json"]["table"]["name"] == "求职工作台"
    assert post.call_args.kwargs["headers"]["Content-Type"] == "application/json; charset=utf-8"


def test_client_manages_fields_and_views_with_explicit_table_id():
    get = Mock(
        side_effect=[
            _response({"code": 0, "data": {"items": [{"field_id": "fld-1", "field_name": "岗位"}]}}),
            _response({"code": 0, "data": {"items": [{"view_id": "vew-1", "view_name": "待处理"}]}}),
        ]
    )
    post = Mock(side_effect=[_response({"code": 0, "data": {"field": {"field_id": "fld-2"}}}), _response({"code": 0, "data": {"view": {"view_id": "vew-2"}}})])
    put = Mock(return_value=_response({"code": 0, "data": {"field": {"field_id": "fld-1"}}}))
    patch = Mock(return_value=_response({"code": 0, "data": {"view": {"view_id": "vew-1"}}}))
    client = FeishuBitableClient(_config(), get=get, post=post, put=put, patch=patch)

    assert client.list_fields("tbl-target")[0]["field_id"] == "fld-1"
    assert client.create_field("tbl-target", {"field_name": "公司", "type": 1})["field_id"] == "fld-2"
    assert client.update_field("tbl-target", "fld-1", {"field_name": "岗位", "type": 1})["field_id"] == "fld-1"
    assert client.list_views("tbl-target")[0]["view_id"] == "vew-1"
    assert client.create_view("tbl-target", {"view_name": "收藏", "view_type": "grid"})["view_id"] == "vew-2"
    assert client.update_view("tbl-target", "vew-1", {"view_name": "待处理"})["view_id"] == "vew-1"
    assert "/tables/tbl-target/fields/fld-1" in put.call_args.args[0]
    assert "/tables/tbl-target/views/vew-1" in patch.call_args.args[0]


def test_client_deletes_table_and_view():
    delete = Mock(side_effect=[_response({"code": 0, "data": {}}), _response({"code": 0, "data": {}})])
    client = FeishuBitableClient(_config(), delete=delete)

    client.delete_view("tbl-target", "vew-old")
    client.delete_table("tbl-old")

    assert "/tables/tbl-target/views/vew-old" in delete.call_args_list[0].args[0]
    assert delete.call_args_list[1].args[0].endswith("/tables/tbl-old")


def test_client_gets_full_view_properties_for_verification():
    get = Mock(
        return_value=_response(
            {
                "code": 0,
                "data": {
                    "view": {
                        "view_id": "vew-1",
                        "view_name": "待处理",
                        "view_type": "grid",
                        "property": {"hidden_fields": ["fld-internal"]},
                    }
                },
            }
        )
    )
    client = FeishuBitableClient(_config(), get=get)

    view = client.get_view("tbl-target", "vew-1")

    assert view["property"]["hidden_fields"] == ["fld-internal"]
    assert get.call_args.args[0].endswith("/tables/tbl-target/views/vew-1")


def test_client_classifies_write_conflict_as_retryable_without_retry_when_disabled():
    post = Mock(return_value=_response({"code": 1254291, "msg": "Write conflict"}))
    client = FeishuBitableClient(_config(), post=post, max_retries=0)

    with pytest.raises(FeishuApiError) as error:
        client.create_table({"table": {"name": "求职工作台"}})

    assert error.value.code == 1254291
    assert error.value.retryable is True
    assert "Write conflict" in str(error.value)


def test_client_reports_permission_error_as_non_retryable():
    post = Mock(return_value=_response({"code": 1254302, "msg": "RolePermNotAllow"}))
    client = FeishuBitableClient(_config(), post=post)

    with pytest.raises(FeishuApiError) as error:
        client.create_table({"table": {"name": "求职工作台"}})

    assert error.value.code == 1254302
    assert error.value.retryable is False
    assert "1254302" in str(error.value)
