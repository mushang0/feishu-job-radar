from job_monitor.workspace_schema import desired_workspace


def test_desired_workspace_uses_job_title_as_primary_field_and_declares_user_views():
    workspace = desired_workspace()

    assert workspace.primary_field == "岗位"
    assert {field.name for field in workspace.fields} >= {"岗位", "岗位ID", "求职状态", "下一步行动", "备注", "投递入口"}
    assert {view.name for view in workspace.views} == {"待处理", "收藏", "投递进度"}
    assert next(field for field in workspace.fields if field.name == "岗位ID").hidden is True
