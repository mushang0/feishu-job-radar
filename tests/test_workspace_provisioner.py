from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from jobpicky.workspace_provisioner import WorkspaceConflictError, WorkspaceProvisioner, WorkspaceVerificationError
from jobpicky.workspace_schema import desired_workspace


class FakeWorkspaceClient:
    def __init__(self):
        self.config = SimpleNamespace(app_token="base-token", base_url="https://example.feishu.cn/base/base-token")
        self.tables = {}
        self.fields = {}
        self.views = {}
        self.write_count = 0
        self._next = 1

    def _id(self, prefix):
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value

    def list_tables(self):
        return [deepcopy(table) for table in self.tables.values()]

    def create_table(self, payload):
        self.write_count += 1
        table_id = self._id("tbl")
        table = {"table_id": table_id, "name": payload["table"]["name"]}
        self.tables[table_id] = table
        self.fields[table_id] = []
        for index, field in enumerate(payload["table"]["fields"]):
            created = deepcopy(field)
            created["field_id"] = self._id("fld")
            created["is_primary"] = index == 0
            for option in (created.get("property") or {}).get("options") or []:
                option["id"] = self._id("opt")
            self.fields[table_id].append(created)
        view_id = self._id("vew")
        self.views[table_id] = [
            {
                "view_id": view_id,
                "view_name": payload["table"]["default_view_name"],
                "view_type": "grid",
                "property": {},
            }
        ]
        return {"table_id": table_id, "default_view_id": view_id}

    def delete_table(self, table_id):
        self.write_count += 1
        self.tables.pop(table_id)

    def list_fields(self, table_id):
        return deepcopy(self.fields[table_id])

    def create_field(self, table_id, payload):
        self.write_count += 1
        field = deepcopy(payload)
        field["field_id"] = self._id("fld")
        field["is_primary"] = False
        for option in (field.get("property") or {}).get("options") or []:
            option["id"] = self._id("opt")
        self.fields[table_id].append(field)
        return deepcopy(field)

    def update_field(self, table_id, field_id, payload):
        self.write_count += 1
        field = next(item for item in self.fields[table_id] if item["field_id"] == field_id)
        field.update(deepcopy(payload))
        return deepcopy(field)

    def delete_field(self, table_id, field_id):
        self.write_count += 1
        self.fields[table_id] = [field for field in self.fields[table_id] if field["field_id"] != field_id]

    def list_views(self, table_id):
        return [{key: value for key, value in view.items() if key != "property"} for view in deepcopy(self.views[table_id])]

    def get_view(self, table_id, view_id):
        return deepcopy(next(view for view in self.views[table_id] if view["view_id"] == view_id))

    def create_view(self, table_id, payload):
        self.write_count += 1
        view = {"view_id": self._id("vew"), **deepcopy(payload), "property": {}}
        self.views[table_id].append(view)
        return deepcopy(view)

    def update_view(self, table_id, view_id, payload):
        self.write_count += 1
        view = next(item for item in self.views[table_id] if item["view_id"] == view_id)
        view.update(deepcopy(payload))
        return deepcopy(view)


def _complete_workspace():
    client = FakeWorkspaceClient()
    created = client.create_table(desired_workspace().table_create_payload())
    table_id = created["table_id"]
    WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)
    return client, table_id


def test_provision_creates_and_verifies_complete_workspace():
    client = FakeWorkspaceClient()
    saved = []

    result = WorkspaceProvisioner(client, desired_workspace()).provision(None, on_table_created=saved.append)

    assert result.table_created is True
    assert saved == [result.table_id]
    assert {field["field_name"] for field in client.list_fields(result.table_id)} == set(desired_workspace().field_names)
    assert {view["view_name"] for view in client.list_views(result.table_id)} == {"待处理", "收藏", "投递进度"}
    assert next(view for view in client.list_views(result.table_id) if view["view_name"] == "投递进度")["view_type"] == "kanban"
    assert result.workspace_url == f"https://example.feishu.cn/base/base-token?table={result.table_id}"
    pending = next(view for view in client.views[result.table_id] if view["view_name"] == "待处理")
    status_field = next(field for field in client.fields[result.table_id] if field["field_name"] == "求职状态")
    pending_status_value = pending["property"]["filter_info"]["conditions"][0]["value"]
    assert json.loads(pending_status_value) == [status_field["property"]["options"][0]["id"]]
    assert "待处理" not in pending_status_value
    progress = next(view for view in client.views[result.table_id] if view["view_name"] == "投递进度")
    assert "hidden_fields" not in progress["property"]
    progress_filter = progress["property"]["filter_info"]
    assert progress_filter["conjunction"] == "and"
    assert len(progress_filter["conditions"]) == 1
    assert progress_filter["conditions"][0]["operator"] == "isNot"
    assert all(len(json.loads(condition["value"])) == 1 for condition in progress_filter["conditions"])


def test_provision_is_idempotent_and_preserves_extra_resources():
    client, table_id = _complete_workspace()
    client.create_field(table_id, {"field_name": "用户自定义", "type": 1})

    first = WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)
    writes_after_first = client.write_count
    second = WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)

    assert first.table_id == second.table_id == table_id
    assert client.write_count == writes_after_first
    assert [field["field_name"] for field in client.list_fields(table_id)].count("用户自定义") == 1


def test_provision_repairs_missing_field_and_view():
    client, table_id = _complete_workspace()
    client.fields[table_id] = [field for field in client.fields[table_id] if field["field_name"] != "备注"]
    client.views[table_id] = [view for view in client.views[table_id] if view["view_name"] != "收藏"]

    result = WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)

    assert result.fields_created == ("备注",)
    assert result.views_created == ("收藏",)
    assert "备注" in {field["field_name"] for field in client.list_fields(table_id)}


def test_provision_removes_legacy_graduate_field_and_moves_recommendation_last():
    client, table_id = _complete_workspace()
    client.create_field(table_id, {"field_name": "届别", "type": 1})

    result = WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)

    fields = client.list_fields(table_id)
    assert "届别" not in {field["field_name"] for field in fields}
    assert fields[-1]["field_name"] == "当前推荐"
    assert "届别" in result.fields_deleted
    assert "当前推荐" in result.fields_deleted


def test_provision_refuses_same_name_table_without_saved_identity():
    client = FakeWorkspaceClient()
    client.create_table(desired_workspace().table_create_payload())

    with pytest.raises(WorkspaceConflictError, match="求职工作台"):
        WorkspaceProvisioner(client, desired_workspace()).provision(None, on_table_created=lambda _: None)


def test_provision_refuses_destructive_field_type_change():
    client, table_id = _complete_workspace()
    status = next(field for field in client.fields[table_id] if field["field_name"] == "求职状态")
    status["type"] = 1

    with pytest.raises(WorkspaceConflictError, match="求职状态"):
        WorkspaceProvisioner(client, desired_workspace()).provision(table_id, on_table_created=lambda _: None)


def test_verify_detects_remote_view_drift():
    client, table_id = _complete_workspace()
    pending = next(view for view in client.views[table_id] if view["view_name"] == "待处理")
    pending["property"]["filter_info"]["conditions"] = []

    with pytest.raises(WorkspaceVerificationError, match="待处理"):
        WorkspaceProvisioner(client, desired_workspace()).verify(table_id)
