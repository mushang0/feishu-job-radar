# User-Friendly Feishu Initialization Design

## Goal

Turn Feishu Job Radar into a deliverable local application whose first-run flow creates and verifies a usable job workspace inside a user-provided Feishu Base, then scans and synchronizes recommended jobs without depending on an old table or personal-data migration.

## Product Boundary

- The user provides job preferences, a standard `https://<tenant>.feishu.cn/base/<app_token>` URL, and Feishu App ID/App Secret.
- The application creates a managed data table inside that Base. It does not create a separate Base by default.
- The first release supports Base URLs only. Wiki URLs receive a clear conversion error.
- Old-table migration, restoration from personal backups, OAuth, SaaS hosting, and a web configuration UI are out of scope.
- Windows 10/11 with Python 3.11 or 3.12 is the primary supported environment. Ubuntu with Python 3.11 is a CI compatibility target.

## First-Run Experience

`python -m job_monitor init` is the single first-run entry point.

1. If required configuration is missing, an interactive wizard collects preferences, Base URL, App ID, and App Secret.
2. The application validates local inputs and performs read-only Feishu authentication and Base access checks.
3. It prints a change preview containing the target Base, managed table name, schema operations, and candidate synchronization scope.
4. The user confirms once. Non-interactive execution requires `--yes`.
5. The application creates or reconciles the managed workspace and reads it back for verification.
6. Only after structural verification succeeds does it run the initial scan, match jobs, and synchronize eligible recommendations.
7. It prints created, updated, skipped, and failed counts plus a direct workspace URL.

Configuration exposes only user choices and required connection information. The application derives the app token from the Base URL and writes the managed table ID and schema version back to the Git-ignored local configuration atomically. Tenant access tokens are not persisted.

## Architecture

### CLI orchestration

The CLI owns prompting, preview/confirmation, sequencing, exit codes, and user-facing summaries. It does not construct Feishu request payloads directly.

### Feishu API client

`FeishuBitableClient` owns authentication and typed operations for Base metadata, tables, fields, views, and records. All writes to one Base are serialized. Transient rate-limit, write-conflict, data-not-ready, timeout, and retryable network errors use bounded exponential backoff. Permission and validation errors fail immediately with redacted, actionable messages.

### Declarative workspace provisioner

`WorkspaceProvisioner` compares the desired schema with remote state, applies only required changes, and verifies the result through GET requests. The table ID is persisted immediately after creation; the schema version is persisted only after complete verification.

Repeated initialization uses the saved table ID and repairs missing managed resources without duplicating them. Extra user-created fields and views are preserved. A conflicting managed field is updated in place only when Feishu can do so without recreating or clearing it; otherwise initialization stops. If no table ID is saved but a same-name table exists, interactive mode may adopt it only after its schema fingerprint matches and the user confirms. Non-interactive mode fails.

## Workspace Schema

The managed table name is `求职工作台`, with `岗位` as the primary text field.

User-facing fields:

- 岗位, 公司, 城市, 届别, 批次
- 推荐理由, 投递入口, 截止时间
- 求职状态, 下次行动, 备注

Managed internal fields, hidden from task-focused views:

- 岗位ID, 来源详情, 首次发现, 最后更新, 推荐有效

The only user status values are:

`待处理`, `收藏`, `不合适`, `已投递`, `笔试中`, `面试中`, `Offer`, `已结束`.

Views:

- `待处理`: grid view filtered to `求职状态 = 待处理` and `推荐有效 = true`.
- `收藏`: grid view filtered to `求职状态 = 收藏`.
- `投递进度`: kanban view showing tracked states from 收藏 through 已结束, grouped by the single-select 求职状态 field.

Filters and field visibility must be provisioned automatically. If the server API cannot express the desired multi-key sort, that limitation is documented and does not require manual setup. The kanban view must still be visually verified to show status columns before release.

## Synchronization Contract

- A new recommendation is created with `求职状态 = 待处理` and `推荐有效 = true`.
- System updates may change job facts and 推荐有效.
- System updates never write 求职状态, 下次行动, or 备注 for an existing record.
- Records are matched by 岗位ID and record ID, never by row order.
- Before creating records, synchronization reads the remote 岗位ID-to-record-ID map. Existing jobs are updated and only missing jobs are created.
- Ambiguous timeout results are reconciled by reading remote state before retrying.
- A job that is no longer recommended and is not actively tracked is retained with 推荐有效 set to false rather than deleted.
- Unknown or duplicated remote identifiers are reported and quarantined from destructive updates.
- Partial failures remain locally retryable and cause a non-zero command exit code.

## Failure and Data Safety

Workspace structural failure stops scanning and synchronization. A crash after table creation is recoverable because the table ID is already saved. Configuration writes use a temporary file and atomic replacement, preserve UTF-8, and never log secrets.

The existing personal database and backup are not inputs to product initialization or release acceptance. Real acceptance uses a separate copy of the sanitized seed database. One-time cleanup of existing remote test artifacts is an explicitly controlled acceptance step, not a public CLI feature. Because Feishu does not allow deleting the last table in a Base, cleanup creates a temporary placeholder, deletes the two obsolete test tables, and removes the placeholder only after the new workspace passes verification.

## Verification and Release Criteria

Automated tests cover Base URL parsing, guided configuration, atomic persistence, UTF-8 payloads, API pagination and error classification, provisioning and retry behavior, schema conflicts, view properties, sync deduplication, user-field protection, CLI confirmation, failure blocking, and exit codes.

The existing regression suite must remain green. CI covers Windows/Python 3.11 and 3.12 plus Ubuntu/Python 3.11.

Real Feishu acceptance uses a fresh configuration and sanitized seed-database copy:

1. Run full initialization and verify the table, field types, status options, three views, filters, field visibility, and candidate count by API readback and visual inspection.
2. Run initialization again and confirm the same table ID with no duplicate fields, views, or records.
3. Manually edit one remote status, next action, and note; run a daily synchronization and verify those values remain unchanged while system fields update.
4. Run the complete test and CI-equivalent checks, review tracked changes for secrets, and verify the public documentation from a clean Windows setup.

Release is complete only when a new user can follow the public README without developer assistance, initialize a usable workspace, safely rerun commands, and keep all user-managed fields intact.
