# User-Friendly Feishu Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe first-run command that provisions a verified Feishu job workspace inside a user-provided Base, creates initial recommendations, and synchronizes them without old-table migration.

**Architecture:** Keep the current local crawler, matcher, and SQLite repository. Extend the existing Feishu HTTP client with structural APIs, add a declarative `WorkspaceProvisioner`, isolate record mapping from Excel export, and make the CLI orchestrate configuration, confirmation, provisioning, scanning, and synchronization in that order.

**Tech Stack:** Python 3.11+, `requests`, `PyYAML`, SQLite, `argparse`, `pytest`, GitHub Actions.

## Global Constraints

- Accept only standard HTTPS Feishu Base URLs whose path is `/base/<app_token>`; reject wiki URLs with a conversion message.
- Never persist tenant access tokens or print App Secret, access token, or full webhook URLs.
- Never overwrite `求职状态`, `下次行动`, or `备注` on an existing remote record.
- Never associate records by row order; use `岗位ID` and `record_id`.
- Serialize writes to one Base and use bounded retry only for transient API failures.
- Do not implement old-table migration or personal-backup restoration.
- Windows 10/11 with Python 3.11/3.12 is the primary release target; Ubuntu/Python 3.11 remains a CI compatibility target.
- Every production behavior change follows RED → GREEN → REFACTOR and each task ends with a green commit.

---

## File Structure

- `src/job_monitor/feishu.py`: authentication, HTTP transport, table/field/view/record API methods, error classification.
- `src/job_monitor/workspace_schema.py`: immutable desired field/view declarations and Feishu payload builders.
- `src/job_monitor/workspace_provisioner.py`: remote comparison, reconciliation, verification, and result reporting.
- `src/job_monitor/onboarding.py`: Base URL parsing, interactive prompts, preview, confirmation, and config persistence.
- `src/job_monitor/feishu_records.py`: target workspace record mapping and remote ID reconciliation.
- `src/job_monitor/config.py`: minimal public defaults, validation, and atomic UTF-8 save.
- `src/job_monitor/storage.py`: candidate/reconciliation queries and recommendation-active state.
- `src/job_monitor/pipeline.py`: initial recommendation creation.
- `src/job_monitor/cli.py`: first-run orchestration and command summaries.
- `tests/test_feishu_workspace_api.py`, `tests/test_workspace_provisioner.py`, `tests/test_onboarding.py`, `tests/test_feishu_records.py`: focused new tests.

---

### Task 1: Feishu workspace management API

**Files:**
- Modify: `src/job_monitor/feishu.py`
- Create: `tests/test_feishu_workspace_api.py`
- Modify: `tests/test_feishu.py`

**Interfaces:**
- Produces: `FeishuApiError(code: int | None, message: str, retryable: bool)`.
- Produces: `FeishuBitableClient.get_app() -> dict[str, Any]`.
- Produces: `list_tables()`, `create_table(payload)`, `delete_table(table_id)`.
- Produces: `list_fields(table_id)`, `create_field(table_id, payload)`, `update_field(table_id, field_id, payload)`.
- Produces: `list_views(table_id)`, `create_view(table_id, payload)`, `update_view(table_id, view_id, payload)`, `delete_view(table_id, view_id)`.
- Produces: `list_all_records(table_id: str | None = None)` and existing batch record methods with optional `table_id`.

- [ ] **Step 1: Write failing structural API tests**

Add tests that inject fake HTTP callables and assert exact endpoints and UTF-8-preserving JSON values:

```python
def test_client_lists_and_creates_tables():
    get = Mock(return_value=response({"code": 0, "data": {"items": [{"table_id": "tbl1", "name": "现有表"}]}}))
    post = Mock(return_value=response({"code": 0, "data": {"table_id": "tbl2"}}))
    client = FeishuBitableClient(config(), get=get, post=post)
    assert client.list_tables() == [{"table_id": "tbl1", "name": "现有表"}]
    assert client.create_table({"table": {"name": "求职工作台"}})["table_id"] == "tbl2"
    assert post.call_args.kwargs["json"]["table"]["name"] == "求职工作台"

def test_client_classifies_write_conflict_as_retryable():
    post = Mock(return_value=response({"code": 1254291, "msg": "Write conflict"}))
    with pytest.raises(FeishuApiError) as error:
        FeishuBitableClient(config(), post=post).create_table({"table": {"name": "求职工作台"}})
    assert error.value.retryable is True
```

Cover pagination, PATCH/PUT/DELETE selection, HTTP errors, 1254302 permission errors, and retryable codes `1254290`, `1254291`, `1254607`, `1254608`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_feishu_workspace_api.py -q`

Expected: collection/import failure because `FeishuApiError` and structural methods do not exist.

- [ ] **Step 3: Implement minimal structural transport**

Add a redacting exception and one internal request path:

```python
class FeishuApiError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable

RETRYABLE_CODES = frozenset({1254290, 1254291, 1254607, 1254608})
```

`_request_json` must authenticate, call the injected verb, run `raise_for_status`, parse JSON, reject non-zero API codes, and retry transient failures with delays `0.25`, `0.5`, `1.0` seconds. Expose resource-specific methods that return the response `data` objects without logging credentials.

- [ ] **Step 4: Preserve record API behavior**

Update existing record methods to accept an optional table ID while keeping `FeishuResult` behavior for callers. Update existing mocks only where the method signature changes.

- [ ] **Step 5: Run focused and full tests**

Run:

```powershell
python -m pytest tests/test_feishu_workspace_api.py tests/test_feishu.py -q
python -m pytest -q
```

Expected: all tests pass with no warnings.

- [ ] **Step 6: Commit**

```powershell
git add src/job_monitor/feishu.py tests/test_feishu.py tests/test_feishu_workspace_api.py
git commit -m "feat: add Feishu workspace management APIs"
```

---

### Task 2: Declarative workspace schema

**Files:**
- Modify: `src/job_monitor/workspace_schema.py`
- Modify: `tests/test_workspace_schema.py`

**Interfaces:**
- Produces: `WORKSPACE_SCHEMA_VERSION = "1"`.
- Produces: `WorkspaceField(name, field_type, type_code, property, hidden_in_views)`.
- Produces: `WorkspaceView(name, view_type, status_values, require_recommended, visible_fields)`.
- Produces: `WorkspaceSchema.table_create_payload()` and field/view payload helpers.

- [ ] **Step 1: Write failing schema payload tests**

Assert the complete field contract, single-select options, numeric Feishu type codes, and view definitions:

```python
def test_workspace_schema_has_exact_user_status_options():
    schema = desired_workspace()
    status = schema.field("求职状态")
    assert status.type_code == 3
    assert [option["name"] for option in status.property["options"]] == [
        "待处理", "收藏", "不合适", "已投递", "笔试中", "面试中", "Offer", "已结束"
    ]

def test_table_payload_is_utf8_safe_and_uses_job_as_primary():
    payload = desired_workspace().table_create_payload()
    assert payload["table"]["name"] == "求职工作台"
    assert payload["table"]["default_view_name"] == "待处理"
    assert payload["table"]["fields"][0] == {"field_name": "岗位", "type": 1}
```

Use type codes text `1`, single select `3`, date `5`, checkbox `7`, URL `15`.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_workspace_schema.py -q`

Expected: failures for missing property/type/payload helpers.

- [ ] **Step 3: Implement the immutable schema**

Declare exactly these fields:

```text
岗位:text(primary), 公司:text, 城市:text, 届别:text, 批次:text,
推荐理由:text, 投递入口:url, 截止时间:date, 求职状态:single_select,
下次行动:text, 备注:text, 岗位ID:text, 来源详情:url,
首次发现:date, 最后更新:date, 推荐有效:checkbox
```

Declare `待处理` and `收藏` as grid views and `投递进度` as kanban. Store visible-field names so the provisioner can translate them to remote field IDs and derive `hidden_fields`.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest tests/test_workspace_schema.py -q
python -m pytest -q
git add src/job_monitor/workspace_schema.py tests/test_workspace_schema.py
git commit -m "feat: define managed Feishu workspace schema"
```

---

### Task 3: Idempotent WorkspaceProvisioner

**Files:**
- Create: `src/job_monitor/workspace_provisioner.py`
- Create: `tests/test_workspace_provisioner.py`

**Interfaces:**
- Consumes: Task 1 client methods and Task 2 schema.
- Produces: `ProvisioningResult(table_id, table_created, fields_created, fields_updated, views_created, views_updated, workspace_url)`.
- Produces: `WorkspaceConflictError` and `WorkspaceVerificationError`.
- Produces: `WorkspaceProvisioner.provision(table_id: str | None, *, on_table_created: Callable[[str], None])`.
- Produces: `WorkspaceProvisioner.verify(table_id) -> None`.

- [ ] **Step 1: Write failing new-table and rerun tests**

Use an in-memory fake client representing tables, fields, and views:

```python
def test_provision_creates_and_verifies_workspace():
    client = FakeWorkspaceClient()
    saved = []
    result = WorkspaceProvisioner(client, desired_workspace()).provision(None, on_table_created=saved.append)
    assert result.table_created is True
    assert saved == [result.table_id]
    assert set(client.field_names(result.table_id)) == set(desired_workspace().field_names)
    assert client.view_names(result.table_id) == {"待处理", "收藏", "投递进度"}

def test_provision_is_idempotent_and_preserves_extra_resources():
    client = FakeWorkspaceClient.with_complete_workspace(extra_field="用户自定义")
    first = WorkspaceProvisioner(client, desired_workspace()).provision(client.table_id, on_table_created=fail)
    second = WorkspaceProvisioner(client, desired_workspace()).provision(client.table_id, on_table_created=fail)
    assert first.table_id == second.table_id
    assert client.field_names(client.table_id).count("用户自定义") == 1
    assert client.write_count_after(first) == 0
```

Also cover partial repair, conflicting non-empty field, same-name collision without saved ID, filters using remote field IDs, hidden fields, wrong view type, and verification mismatch.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_workspace_provisioner.py -q`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement table and field reconciliation**

When `table_id` is absent, list tables. If `求职工作台` already exists, raise `WorkspaceConflictError`; otherwise create it from `table_create_payload` and invoke `on_table_created` before any further request. Resolve remote fields by exact Unicode name. Create missing fields, safely update compatible managed fields, preserve extras, and reject destructive type conflicts.

- [ ] **Step 4: Implement view reconciliation and verification**

Reuse the default `待处理` view returned by table creation. Create missing `收藏` and `投递进度` views. PATCH filters and hidden fields using field IDs. Verify table name, primary field, field type/options, view type, filter conditions, and hidden-field membership through fresh list/get calls.

- [ ] **Step 5: Run focused/full tests and commit**

```powershell
python -m pytest tests/test_workspace_provisioner.py tests/test_workspace_schema.py -q
python -m pytest -q
git add src/job_monitor/workspace_provisioner.py tests/test_workspace_provisioner.py
git commit -m "feat: provision Feishu workspace idempotently"
```

---

### Task 4: Guided configuration and safe persistence

**Files:**
- Modify: `src/job_monitor/config.py`
- Create: `src/job_monitor/onboarding.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_onboarding.py`

**Interfaces:**
- Produces: `parse_base_url(value: str) -> ParsedBaseUrl(origin: str, app_token: str)`.
- Produces: `save_config(config, path) -> None` using UTF-8 temporary file plus `os.replace`.
- Produces: `collect_missing_config(config, input_fn=input, output_fn=print) -> dict`.
- Produces: `confirm_initialization(preview, *, assume_yes, input_fn=input) -> bool`.
- Produces: `public_config_template() -> dict`.

- [ ] **Step 1: Write failing URL and persistence tests**

```python
@pytest.mark.parametrize("url", [
    "https://example.feishu.cn/base/bascnToken",
    "https://example.feishu.cn/base/bascnToken?table=tblOld&view=vewOld",
])
def test_parse_base_url_extracts_only_app_token(url):
    parsed = parse_base_url(url)
    assert parsed.app_token == "bascnToken"
    assert parsed.origin == "https://example.feishu.cn"

def test_parse_base_url_rejects_wiki_link():
    with pytest.raises(ConfigError, match="base"):
        parse_base_url("https://example.feishu.cn/wiki/wikcnToken")

def test_save_config_is_utf8_and_never_persists_tenant_token(tmp_path):
    path = tmp_path / "config.yaml"
    save_config({"user_profile": {"role_groups": ["硬件/嵌入式"]}, "feishu": {"tenant_access_token": "secret"}}, path)
    text = path.read_text(encoding="utf-8")
    assert "硬件/嵌入式" in text
    assert "tenant_access_token" not in text
```

Cover invalid scheme/host/path, required profile fields, prompt defaults, declined confirmation, complete non-interactive configuration, and preservation of unknown advanced settings.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_config.py tests/test_onboarding.py -q`

- [ ] **Step 3: Implement minimal public config and parser**

Keep taxonomy and crawler tuning as internal defaults. Remove them from the public template, not from runtime defaults. Replace user-facing `bitable_app_token`, `table_id`, and `tenant_access_token` with `base_url`, `workspace_table_id`, and `workspace_schema_version`. Keep App ID/App Secret and optional webhook.

- [ ] **Step 4: Implement wizard, preview, and atomic save**

Prompt only for graduate years, batches, role groups, optional cities/companies, Base URL, App ID, and App Secret. Never echo the secret. Confirmation accepts `y/yes/是`; `--yes` bypasses the prompt only after validation and preview generation.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest tests/test_config.py tests/test_onboarding.py tests/test_diagnostics.py -q
python -m pytest -q
git add src/job_monitor/config.py src/job_monitor/onboarding.py tests/test_config.py tests/test_onboarding.py
git commit -m "feat: add guided first-run configuration"
```

---

### Task 5: Managed workspace record mapping and reconciliation

**Files:**
- Create: `src/job_monitor/feishu_records.py`
- Modify: `src/job_monitor/storage.py`
- Modify: `src/job_monitor/audit.py`
- Modify: `src/job_monitor/cli.py`
- Create: `tests/test_feishu_records.py`
- Modify: `tests/test_sync_candidates.py`, `tests/test_feishu.py`, `tests/test_feishu_audit.py`

**Interfaces:**
- Produces: `build_create_fields(row) -> dict[str, Any]`.
- Produces: `build_update_fields(row) -> dict[str, Any]` without user-managed fields.
- Produces: `index_remote_records(records) -> RemoteRecordIndex` with duplicate/unmatched diagnostics.
- Produces: `JobRepository.list_feishu_reconciliation_rows() -> list[dict]`.
- Updates: `_sync_feishu` reads remote state before deciding create/update and returns `SyncSummary`.

- [ ] **Step 1: Write failing record-contract tests**

```python
def test_new_record_uses_managed_schema_and_defaults_to_pending():
    fields = build_create_fields(job_row(user_status=None, recommendation_active=True))
    assert fields["岗位"] == "FPGA工程师"
    assert fields["岗位ID"] == "42"
    assert fields["求职状态"] == "待处理"
    assert fields["推荐有效"] is True
    assert "用户状态" not in fields

def test_update_never_contains_user_managed_fields():
    fields = build_update_fields(job_row(user_status="收藏", note="keep", next_action="面试"))
    assert {"求职状态", "下次行动", "备注"}.isdisjoint(fields)

def test_remote_index_rejects_duplicate_job_ids():
    index = index_remote_records([record("rec1", 42), record("rec2", 42)])
    assert index.duplicate_job_ids == {42}
```

Add repository tests proving reconciliation includes new recommendations, actively tracked jobs, and already-synced jobs that are no longer recommended so `推荐有效=false` can be written.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_feishu_records.py tests/test_sync_candidates.py tests/test_feishu.py -q`

- [ ] **Step 3: Implement workspace record mapping**

Map title/company/location/profile fields, choose 投递入口 from reliable official/apply URL then source URL, emit dates as millisecond timestamps and links as `{link, text}`. Existing remote record updates omit all user-managed fields.

- [ ] **Step 4: Implement remote-first synchronization**

Read all remote records once, detect duplicates, and choose actions by 岗位ID. Reconcile an uncertain batch by reading remote state before retry. Mark local sync state only after the record ID is known. Unknown/duplicate IDs are skipped with failures, never deleted.

- [ ] **Step 5: Remove legacy status migration aliases**

`normalize_status` accepts only the eight current statuses. Update audit/recovery tests accordingly. This removes old personal-table compatibility while retaining safe state pull for current workspaces.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_feishu_records.py tests/test_sync_candidates.py tests/test_feishu.py tests/test_feishu_audit.py -q
python -m pytest -q
git add src/job_monitor/feishu_records.py src/job_monitor/storage.py src/job_monitor/audit.py src/job_monitor/cli.py tests
git commit -m "feat: sync jobs to managed Feishu workspace"
```

---

### Task 6: Complete first-run orchestration

**Files:**
- Modify: `src/job_monitor/pipeline.py`
- Modify: `src/job_monitor/cli.py`
- Modify: `src/job_monitor/diagnostics.py`
- Modify: `tests/test_incremental_init.py`, `tests/test_cli.py`, `tests/test_diagnostics.py`

**Interfaces:**
- Updates: `InitSummary` adds `recommended_items`.
- Updates: `run_init_with_page_batches(..., run_date=None)` persists the complete initial recommendation set.
- Updates: CLI `init` adds `--yes` and runs configure → preflight → confirm → provision → scan → sync.

- [ ] **Step 1: Write the failing initial-recommendation test**

```python
def test_init_pipeline_persists_recommendations_for_first_sync(tmp_path, mock_config):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    summary = run_init_with_page_batches(repo, [[matching_job()]], mock_config(), run_date="2026-07-11")
    assert summary.recommended_items == 1
    assert len(repo.list_feishu_sync_candidates()) == 1
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_incremental_init.py -q`

Expected: missing argument/property and no recommendation row.

- [ ] **Step 3: Implement initial recommendation persistence**

Collect `should_push` matches during all page batches and call `sync_global_recommendations` once after scanning. Preserve incremental job writes so a crawler interruption retains already-seen jobs, but mark the run partial and avoid claiming full success.

- [ ] **Step 4: Write failing CLI order and failure tests**

Assert:

```text
read-only preflight occurs before confirmation
provision occurs before crawler creation/use
failed provisioning never calls crawler or sync
successful scan calls sync with reconciliation rows
declined confirmation performs no remote write
--yes skips input but not validation/preview
```

- [ ] **Step 5: Implement CLI orchestration**

Construct the provisioner with the parsed app token. Save table ID from the callback immediately and schema version after verification. On success, update the in-memory config before creating the record client. Return `1` for structural or partial synchronization failure and `0` only for verified completion.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_incremental_init.py tests/test_cli.py tests/test_diagnostics.py -q
python -m pytest -q
git add src/job_monitor/pipeline.py src/job_monitor/cli.py src/job_monitor/diagnostics.py tests/test_incremental_init.py tests/test_cli.py tests/test_diagnostics.py
git commit -m "feat: initialize and populate Feishu workspace"
```

---

### Task 7: Remove migration scope and finish release documentation

**Files:**
- Delete: `src/job_monitor/migration.py`
- Delete: `tests/test_migration.py`
- Modify: `config.example.yaml`, `README.md`, `pyproject.toml`, `run_daily.bat`, `.github/workflows/tests.yml`
- Create: `tests/test_public_config.py`

**Interfaces:**
- Produces console script: `feishu-job-radar = job_monitor.cli:main`.
- Public docs expose `init`, `daily`, `rematch`, and `export`; `pull`/`check` remain advanced diagnostics.

- [ ] **Step 1: Write failing public-artifact tests**

```python
def test_public_config_contains_only_user_inputs_and_no_credentials():
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    assert "system_taxonomy" not in config
    assert config["feishu"]["base_url"] == ""
    assert config["feishu"]["app_secret"] == ""
    assert "table_id" not in config["feishu"]

def test_readme_does_not_require_manual_table_schema():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "YOUR_TABLE_ID" not in text
    assert "岗位ID（单行文本）" not in text
    assert "migrate-feishu" not in text
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_public_config.py -q`

- [ ] **Step 3: Remove migration-only code and references**

Delete the unused migration module/tests. Do not delete generic SQLite backup, state recovery, or schema-upgrade safeguards.

- [ ] **Step 4: Rewrite public onboarding and troubleshooting**

Document Python installation, application permission setup, adding the application as a Base document application/manager, obtaining a Base URL, running `init`, interpreting results, rerunning safely, and fixing base/wiki URL, 1254302 permission, rate-limit, and network errors. State WonderCV accuracy/privacy limitations and that the bot webhook is optional.

- [ ] **Step 5: Add packaging entry point and CI matrix**

Set the project script and matrix:

```toml
[project.scripts]
feishu-job-radar = "job_monitor.cli:main"
```

CI includes `windows-latest` with Python `3.11`/`3.12` and `ubuntu-latest` with Python `3.11`.

- [ ] **Step 6: Run release checks and commit**

```powershell
python -m pytest -q
python -m pip install -e .
feishu-job-radar --help
python -m job_monitor --help
git diff --check
git add -A
git commit -m "docs: publish user-ready first-run workflow"
```

---

### Task 8: Real Feishu acceptance and final verification

**Files:**
- No committed product files unless acceptance reveals a reproducible defect; any defect first receives a failing automated test and its own focused fix commit.
- Keep real configuration, backups, IDs, logs, and acceptance database outside tracked paths.

**Interfaces:**
- Consumes the completed CLI and public documentation.
- Produces a final acceptance summary in the task handoff, not a repository file containing personal metadata.

- [ ] **Step 1: Verify backup and identify exact remote test tables read-only**

Validate that `data/backups/feishu-pre-migration-records-20260710T091639Z.json` exists, parses, and has a SHA-256. List remote tables and identify only:

1. the legacy table whose read-only record count matches the documented 708-record baseline;
2. the malformed trial table whose structure/record count matches the documented 150-record test artifact.

If identification is ambiguous, stop before deletion and request the exact table IDs.

- [ ] **Step 2: Perform the authorized clean-room remote setup**

Create a temporary empty placeholder table, delete only the two identified obsolete tables, list tables again, and verify both IDs are absent. Never expose the deletion helper as a public command.

- [ ] **Step 3: Create isolated local acceptance inputs**

Copy tracked `data/jobs_seed.sqlite` to an OS temporary directory. Create a fresh Git-ignored/temp config using neutral preferences and the real Base URL/App credentials, with no workspace table ID or schema version. Do not copy personal user-state rows or read backup states into this database.

- [ ] **Step 4: Run first initialization**

Run:

```powershell
python -m job_monitor --config <temp-config> --db <temp-db> init --yes
```

Expected: exit `0`; a new `求职工作台`; exact managed fields and three views; every newly synchronized recommendation has `求职状态=待处理`; remote unique 岗位ID count equals local candidate count.

- [ ] **Step 5: Run idempotency acceptance**

Run the same command again. Expected: same table ID, no duplicate fields/views/records, and a success summary with zero unintended creations.

- [ ] **Step 6: Run user-field protection acceptance**

In Feishu, edit one record's 求职状态, 下次行动, and 备注. Change one system-managed local field, then run `daily` or a deterministic sync path. Verify the three user fields remain byte-for-byte equivalent by API readback while the system field updates.

- [ ] **Step 7: Visual and cleanup acceptance**

Open all three views in Feishu. Verify Chinese labels, visible columns, filters, and the kanban status columns. After the managed table passes, delete the temporary placeholder and confirm the managed table remains.

- [ ] **Step 8: Run final verification**

Run:

```powershell
python -m pytest -q
git diff --check
git status --short
git log --oneline --decorate -12
```

Inspect tracked diffs for credentials, tokens, table IDs, personal company/job names, and backup contents. Then use `superpowers:requesting-code-review`, fix any findings through TDD, rerun `superpowers:verification-before-completion`, and finish with `superpowers:finishing-a-development-branch`.
