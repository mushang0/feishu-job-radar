from unittest.mock import Mock
import requests
from job_monitor.cli import _sync_feishu
from job_monitor.feishu import FeishuBitableClient, FeishuConfig
from job_monitor.storage import JobRepository


def test_feishu_client_skips_when_credentials_are_missing():
    client = FeishuBitableClient(FeishuConfig())
    result = client.batch_create_records([{"fields": {"公司": "示例公司"}}])
    assert result.sent is False
    assert result.error == "feishu credentials are not configured"


def test_feishu_client_builds_batch_create_request():
    mock_post = Mock()
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"code": 0, "data": {"records": [{"record_id": "rec1"}]}}
    mock_post.return_value = mock_response

    client = FeishuBitableClient(
        FeishuConfig(app_token="app", table_id="tbl", tenant_access_token="token"),
        post=mock_post,
    )

    result = client.batch_create_records([{"fields": {"公司": "示例公司"}}])

    assert result.sent is True
    assert result.record_ids == ["rec1"]
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0].endswith("/bitable/v1/apps/app/tables/tbl/records/batch_create")
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["json"] == {"records": [{"fields": {"公司": "示例公司"}}]}


def test_feishu_config_reads_app_credentials():
    config = {
        "feishu": {
            "bitable_app_token": "base",
            "table_id": "tbl",
            "app_id": "cli_app",
            "app_secret": "secret",
        }
    }
    feishu = FeishuConfig.from_config(config)
    assert feishu.app_token == "base"
    assert feishu.table_id == "tbl"
    assert feishu.app_id == "cli_app"
    assert feishu.app_secret == "secret"


def test_feishu_client_fetches_tenant_access_token_from_app_credentials():
    mock_post = Mock()
    
    # First response: token auth
    token_response = Mock()
    token_response.json.return_value = {"code": 0, "tenant_access_token": "tenant-token"}
    
    # Second response: batch create
    create_response = Mock()
    create_response.json.return_value = {"code": 0, "data": {"records": [{"record_id": "rec1"}]}}
    
    mock_post.side_effect = [token_response, create_response]

    client = FeishuBitableClient(
        FeishuConfig(app_token="base", table_id="tbl", app_id="cli_app", app_secret="secret"),
        post=mock_post,
    )

    result = client.batch_create_records([{"fields": {"公司": "示例公司"}}])

    assert result.sent is True
    assert result.record_ids == ["rec1"]
    assert mock_post.call_count == 2
    
    # Verify first call (auth)
    auth_call = mock_post.call_args_list[0]
    assert auth_call[0][0].endswith("/auth/v3/tenant_access_token/internal")
    assert auth_call[1]["json"] == {"app_id": "cli_app", "app_secret": "secret"}
    
    # Verify second call (create)
    create_call = mock_post.call_args_list[1]
    assert create_call[0][0].endswith("/records/batch_create")
    assert create_call[1]["headers"]["Authorization"] == "Bearer tenant-token"


def test_feishu_client_returns_error_result_for_http_failure():
    mock_post = Mock()
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.text = '{"code":91403,"msg":"Forbidden"}'
    mock_response.raise_for_status.side_effect = requests.HTTPError("403 Client Error: Forbidden", response=mock_response)
    mock_post.return_value = mock_response

    client = FeishuBitableClient(
        FeishuConfig(app_token="base", table_id="tbl", tenant_access_token="token"),
        post=mock_post,
    )

    result = client.batch_create_records([{"fields": {"公司": "示例公司"}}])

    assert result.sent is False
    assert "403" in result.error
    assert "91403" in result.error


def test_sync_feishu_updates_official_url_but_not_manual_fields(tmp_path, monkeypatch):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    rows = [
        {
            "job_id": 1,
            "company": "TargetCo",
            "title": "工程师",
            "feishu_record_id": "rec1",
            "sync_status": "pending",
            "official_url": "https://auto.example.com",
            "user_status": "manual",
            "note": "keep",
        }
    ]
    captured = {}

    class Client:
        def __init__(self, config):
            pass

        def batch_create_records(self, records):
            raise AssertionError("create should not be called")

        def batch_update_records(self, records):
            captured["records"] = records
            return type("Result", (), {"sent": True})()

    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)

    _sync_feishu(repo, {"feishu": {"tenant_access_token": "token"}}, rows)

    fields = captured["records"][0]["fields"]
    assert fields["官方链接"]["link"] == "https://auto.example.com"
    assert "用户状态" not in fields
    assert "备注" not in fields


def test_sync_feishu_updates_records_by_record_id_not_row_order(tmp_path, monkeypatch):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    rows = [
        {
            "job_id": 2,
            "company": "SecondCo",
            "feishu_record_id": "rec-second",
            "sync_status": "pending",
            "official_url": "https://second.example.com",
        },
        {
            "job_id": 1,
            "company": "FirstCo",
            "feishu_record_id": "rec-first",
            "sync_status": "pending",
            "official_url": "https://first.example.com",
        },
    ]
    captured = {}

    class Client:
        def __init__(self, config):
            pass

        def batch_create_records(self, records):
            raise AssertionError("create should not be called")

        def batch_update_records(self, records):
            captured["records"] = records
            return type("Result", (), {"sent": True})()

    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)

    _sync_feishu(repo, {"feishu": {"tenant_access_token": "token"}}, rows)

    by_record_id = {record["record_id"]: record["fields"]["官方链接"]["link"] for record in captured["records"]}
    assert by_record_id == {
        "rec-second": "https://second.example.com",
        "rec-first": "https://first.example.com",
    }


def test_feishu_client_lists_all_records():
    mock_get = Mock()
    # Mock two page responses, first has_more=True, second has_more=False
    response1 = Mock()
    response1.status_code = 200
    response1.json.return_value = {
        "code": 0,
        "data": {
            "has_more": True,
            "page_token": "token-next",
            "items": [{"record_id": "rec1", "fields": {"岗位ID": "1"}}]
        }
    }
    response2 = Mock()
    response2.status_code = 200
    response2.json.return_value = {
        "code": 0,
        "data": {
            "has_more": False,
            "items": [{"record_id": "rec2", "fields": {"岗位ID": "2"}}]
        }
    }
    mock_get.side_effect = [response1, response2]

    client = FeishuBitableClient(
        FeishuConfig(app_token="app", table_id="tbl", tenant_access_token="token"),
        get=mock_get
    )
    records = client.list_all_records()
    assert len(records) == 2
    assert records[0]["record_id"] == "rec1"
    assert records[1]["record_id"] == "rec2"
    assert mock_get.call_count == 2

