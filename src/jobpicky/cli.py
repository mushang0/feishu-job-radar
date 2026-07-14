from __future__ import annotations

import argparse
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .audit import audit_feishu_records
from .config import load_config, save_config, validate_config
from .diagnostics import preflight_check
from .error_safety import known_secrets, safe_exception_detail
from .exporters import export_jobs_to_excel
from .feishu import FeishuBitableClient, FeishuConfig
from .logging_utils import SensitiveDataFilter, setup_logging
from .onboarding import InitializationPreview, collect_missing_config, confirm_initialization
from .official_search import OfficialUrlFinder
from .pipeline import backfill_existing_job_details, enrich_official_urls, run_init_with_page_batches, pull_user_states_from_feishu
from .core import DatabaseBootstrapService, JobQueryService
from .integrations.feishu import FeishuIntegrationService
from .seed import SeedDatabaseError, find_seed_database, restore_seed_database
from .runtime import RunReport, RunReporter, console_event, console_report
from .services.scanning import DailyWorkflowResult, _notification_rows, run_daily_workflow
from .services.local import rematch_local
from .services.initialization import existing_local_repository
from .storage import JobRepository
from .services.synchronization import SyncSummary, sync_feishu
from .wondercv import WonderCVCrawler
from .workspace_provisioner import WorkspaceProvisioner
from .workspace_schema import WORKSPACE_SCHEMA_VERSION, desired_workspace


@dataclass(frozen=True, slots=True)
class PullSummary:
    updated: int = 0
    skipped: int = 0
    unknown: int = 0
    failed: int = 0


def rematch_existing_jobs(repo: JobRepository, config: dict, recommendation_date: str | None = None):
    """Legacy CLI seam backed by the shared local application service."""
    _repository, summary = rematch_local(repo.db_path, config, recommendation_date)
    return summary


@dataclass(frozen=True, slots=True)
class CliErrorSpec:
    code: str
    message: str


_CLI_ERROR_SPECS = {
    "configuration": CliErrorSpec(
        "configuration_invalid",
        "配置读取失败，请检查 YAML 格式后重试。",
    ),
    "init": CliErrorSpec("initialization_failed", "初始化失败，请查看日志后重试。"),
    "reset": CliErrorSpec("reset_failed", "reset 失败，请查看日志后重试。"),
    "pull": CliErrorSpec("pull_failed", "pull 失败，请查看日志后重试。"),
    "check": CliErrorSpec("check_failed", "check 失败，请查看日志后重试。"),
    "daily": CliErrorSpec("daily_failed", "daily 失败，请查看日志后重试。"),
    "rematch": CliErrorSpec("rematch_failed", "rematch 失败，请查看日志后重试。"),
    "open-workspace": CliErrorSpec(
        "open_workspace_failed", "打开飞书工作台失败，请查看日志后重试。"
    ),
}


def _cli_error_spec(command: str, *, configuration: bool = False) -> CliErrorSpec:
    if configuration:
        return _CLI_ERROR_SPECS["configuration"]
    return _CLI_ERROR_SPECS.get(command, CliErrorSpec("command_failed", "命令执行失败，请查看日志后重试。"))


def _report_cli_exception(
    config: dict,
    exc: BaseException,
    *,
    log_message: str,
    error: CliErrorSpec,
) -> None:
    """Report one stable CLI error while keeping diagnostics log-safe."""
    detail = safe_exception_detail(exc, config)
    logging.error("%s code=%s detail=%s", log_message, error.code, detail)
    print(f"错误 code={error.code} message={error.message}")


def _configure_cli_logging(command: str, config: dict | None = None) -> None:
    """Configure filtered logging before config parsing and after secrets load."""
    log_name = f"{command}-{datetime.now().date().isoformat()}.log"
    log_dir = os.environ.get("JOBPICKY_LOG_DIR", "data/logs")
    try:
        setup_logging(Path(log_dir) / log_name, secrets=known_secrets(config))
    except Exception:
        # Logging setup must not create a second exception boundary escape. The
        # normal path uses setup_logging's sensitive-data filter; keep the same
        # guarantee if the configured log destination is unavailable.
        stream_handler = logging.StreamHandler()
        stream_handler.addFilter(SensitiveDataFilter(known_secrets(config)))
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            handlers=[stream_handler],
            force=True,
        )


def main(argv: list[str] | None = None, reporter: RunReporter | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobpicky")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="data/jobs.sqlite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="配置飞书工作台并从 seed 初始化岗位库",
        description="引导配置并自动创建或修复飞书求职工作台，使用 seed 岗位库重新匹配并同步。",
    )
    init_parser.add_argument("--config", dest="command_config")
    init_parser.add_argument("--db", dest="command_db")
    init_parser.add_argument("--output", default="data/exports/all_jobs_initial.xlsx")
    init_parser.add_argument("--yes", action="store_true", help="验证配置后无需再次确认")

    reset_parser = subparsers.add_parser("reset", help="删除当前测试工作台并从 seed 重新初始化")
    reset_parser.add_argument("--config", dest="command_config")
    reset_parser.add_argument("--db", dest="command_db")
    reset_parser.add_argument("--output", default="data/exports/all_jobs_initial.xlsx")
    reset_parser.add_argument("--yes", action="store_true", help="确认删除当前飞书工作台并恢复 seed 数据库")

    daily_parser = subparsers.add_parser("daily", help="每日增量扫描、飞书同步和提醒")
    daily_parser.add_argument("--config", dest="command_config")
    daily_parser.add_argument("--db", dest="command_db")
    daily_parser.add_argument("--no-feishu", action="store_true", help="只写本地库，不调用飞书")

    rematch_parser = subparsers.add_parser("rematch", help="按当前配置重新匹配历史岗位")
    rematch_parser.add_argument("--config", dest="command_config")
    rematch_parser.add_argument("--db", dest="command_db")
    rematch_parser.add_argument("--date", help="推荐表追加日期，默认今天")
    rematch_parser.add_argument("--no-feishu", action="store_true", help="只写本地库，不调用飞书")
    rematch_parser.add_argument("--no-enrich-official", action="store_true", help="跳过官方链接补充")

    export_parser = subparsers.add_parser("export", help="从 SQLite 导出 Excel")
    export_parser.add_argument("--db", dest="command_db")
    export_parser.add_argument("--output", default="data/exports/all_jobs.xlsx")
    export_parser.add_argument("--table", choices=["all", "recommended", "daily-new", "raw"], default="all")
    export_parser.add_argument("--date")

    pull_parser = subparsers.add_parser("pull", help="从飞书工作台回收求职状态、下次行动和备注")
    pull_parser.add_argument("--config", dest="command_config")
    pull_parser.add_argument("--db", dest="command_db")

    check_parser = subparsers.add_parser("check", help="只读检查飞书记录与本地岗位差异")
    check_parser.add_argument("--config", dest="command_config")
    check_parser.add_argument("--db", dest="command_db")
    open_parser = subparsers.add_parser("open-workspace", help="在浏览器中打开飞书求职工作台")
    open_parser.add_argument("--config", dest="command_config")

    args = parser.parse_args(argv)
    db_path = args.command_db or args.db
    config_path = getattr(args, "command_config", None) or args.config
    if args.command == "export":
        return _run_export(db_path, args.output, args.table, args.date)

    _configure_cli_logging(args.command)
    try:
        config = load_config(config_path)
    except Exception as exc:
        _report_cli_exception(
            {},
            exc,
            log_message=f"{args.command} configuration load failed",
            error=_cli_error_spec(args.command, configuration=True),
        )
        return 1

    # Reconfigure the same log file with exact configured secrets once YAML has
    # loaded successfully. This also protects later records containing values
    # that are not recognizable from their field names alone.
    _configure_cli_logging(args.command, config)
    reporter = reporter or RunReporter(console_event, console_report)

    try:
        if args.command == "init":
            return _run_init(config, db_path, config_path, args.output, assume_yes=args.yes, reporter=reporter)
        if args.command == "reset":
            return _run_reset(config, db_path, config_path, args.output, confirmed=args.yes)
        if args.command == "daily":
            return _run_daily(config, db_path, skip_feishu=args.no_feishu, reporter=reporter)
        if args.command == "rematch":
            return _run_rematch(
                config,
                db_path,
                args.date,
                skip_feishu=args.no_feishu,
                skip_enrich_official=args.no_enrich_official,
                reporter=reporter,
            )
        if args.command == "pull":
            return _run_pull(config, db_path, reporter=reporter)
        if args.command == "check":
            return _run_check(config, db_path, reporter=reporter)
        if args.command == "open-workspace":
            return _run_open_workspace(config)
        return 2
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message=f"{args.command} command failed",
            error=_cli_error_spec(args.command),
        )
        return 1


def _run_export(db_path: str, output_path: str, table: str = "all", export_date: str | None = None) -> int:
    repo = DatabaseBootstrapService(db_path).initialize()
    if table == "recommended":
        rows = JobQueryService(repo).recommendations(export_date)
        export_jobs_to_excel(rows, output_path, table="recommended")
    elif table == "daily-new":
        if not export_date:
            raise SystemExit("--date is required when --table daily-new")
        rows = repo.list_daily_new_jobs(export_date)
        export_jobs_to_excel(rows, output_path)
    elif table == "raw":
        rows = repo.list_jobs_with_matches()
        export_jobs_to_excel(rows, output_path)
    else:
        rows = repo.list_feishu_reconciliation_rows()
        export_jobs_to_excel(rows, output_path)
    return 0


def _run_init(
    config: dict,
    db_path: str,
    config_path: str,
    output_path: str,
    *,
    assume_yes: bool = False,
    seeded_from_reset: bool = False,
    reporter: RunReporter | None = None,
) -> int:
    reporter = reporter or RunReporter()
    try:
        # ``load_config`` supplies non-empty defaults.  A missing config file is
        # nevertheless a first-run experience and must collect the user's own
        # profile instead of silently retaining those defaults.
        configured = collect_missing_config(
            config,
            force_profile_prompts=not Path(config_path).exists(),
        )
        if configured is not config:
            config.clear()
            config.update(configured)
        errors = validate_config(config, require_feishu=True)
        if errors:
            print("配置检查失败：" + "；".join(errors))
            return 1
        save_config(config, config_path)
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="initial configuration failed",
            error=_cli_error_spec("init"),
        )
        return 1

    try:
        repo = existing_local_repository(db_path)
    except ValueError as exc:
        print(str(exc))
        return 1

    reporter.stage("init", 1, 5, "检查本地岗位库", "done", f"{JobQueryService(repo).stats()['jobs']} 条")
    local_preflight = preflight_check(config, db_path)
    if not local_preflight.ok:
        print("运行前检查失败：" + "；".join(local_preflight.errors))
        return 1

    try:
        reporter.stage("init", 2, 5, "检查飞书连接与权限")
        integration = FeishuIntegrationService(
            repo, config, config_path=config_path,
            client_factory=FeishuBitableClient, push_jobs=sync_feishu,
        )
        client = integration.test_connection()
        _read_only_workspace_preflight(client, config)
        reporter.stage("init", 2, 5, "检查飞书连接与权限", "done")
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="Feishu read-only preflight failed",
            error=_cli_error_spec("init"),
        )
        return 1

    preview = InitializationPreview(
        base_url=str(config["feishu"]["base_url"]),
        table_name=desired_workspace().table_name,
        baseline_items=len(repo.list_stored_jobs()),
    )
    if not confirm_initialization(preview, assume_yes=assume_yes):
        print("已取消初始化，未修改飞书结构。")
        return 0

    try:
        reporter.stage("init", 3, 5, "创建或修复飞书工作台并同步本地推荐")
        connected = integration.connect(client=client)
        provisioning = connected
        sync_summary = connected.sync
        reporter.stage("init", 3, 5, "创建或修复飞书工作台并同步本地推荐", "done")
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="Feishu workspace provisioning failed",
            error=_cli_error_spec("init"),
        )
        return 1

    started_at = datetime.now().isoformat(timespec="seconds")
    summary = type("ExistingLocalSummary", (), {
        "items_seen": connected.baseline_items, "new_items": 0, "updated_items": 0,
        "relevant_items": connected.recommended_items,
        "recommended_items": connected.recommended_items,
    })()
    reporter.stage("init", 4, 5, "读取本地推荐结果", "done", f"推荐 {summary.recommended_items} 条")
    reporter.stage("init", 5, 5, "同步到飞书", "done", f"新建 {sync_summary.created} 条")
    export_jobs_to_excel(repo.list_all_jobs(), output_path)
    repo.record_scan_run(
        {
            "run_type": "init",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "partial" if sync_summary.failed else "success",
            "pages_scanned": 0,
            "items_seen": summary.items_seen,
            "new_items": summary.new_items,
            "updated_items": summary.updated_items,
            "error_message": f"飞书同步失败 {sync_summary.failed} 条" if sync_summary.failed else None,
        }
    )
    seed_origin = seeded_from_reset
    print("已连接飞书，工作台创建或修复完成，并已同步现有本地推荐；未执行本地初始化、抓取或重新匹配。")
    print(_format_run_summary("init", summary, None, PullSummary(), sync_summary))
    if summary.items_seen == 0:
        print("提示：本地岗位库为空；请确认运行数据库未被错误替换，或运行 daily 获取新增岗位。")
    print(f"飞书工作台：{provisioning.workspace_url}")
    reporter.finish(RunReport("init", "partial" if sync_summary.failed else "success", items_seen=summary.items_seen, recommended_items=summary.recommended_items, baseline_items=summary.items_seen, current_workspace_items=len(repo.list_feishu_sync_candidates()), feishu_created=sync_summary.created, feishu_updated=sync_summary.updated, feishu_skipped=sync_summary.skipped, feishu_failed=sync_summary.failed, workspace_url=provisioning.workspace_url, advice="请运行“每日扫描”以发现新增岗位。" if not sync_summary.failed else "飞书同步有失败项，请检查错误后安全重试。"))
    logging.info(
        "init finished: seeded=%s seen=%s recommended=%s feishu_created=%s feishu_updated=%s feishu_failed=%s",
        seed_origin,
        summary.items_seen,
        summary.recommended_items,
        sync_summary.created,
        sync_summary.updated,
        sync_summary.failed,
    )
    repo.vacuum()
    return 1 if sync_summary.failed else 0


def _run_reset(
    config: dict,
    db_path: str,
    config_path: str,
    output_path: str,
    *,
    confirmed: bool,
) -> int:
    """Destructively replace the configured test table after explicit confirmation."""
    if not confirmed:
        print("reset 是破坏性操作；请使用 reset --yes 确认删除当前飞书工作台并恢复 seed 数据库。")
        return 2
    errors = validate_config(config)
    if errors:
        print("配置检查失败：" + "；".join(errors))
        return 1
    feishu = config.setdefault("feishu", {})
    if not feishu.get("app_id") or not feishu.get("app_secret"):
        print("配置检查失败：请填写飞书 App ID 和 App Secret。")
        return 1
    try:
        find_seed_database()
    except SeedDatabaseError as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="reset seed lookup failed",
            error=_cli_error_spec("reset"),
        )
        return 1
    workspace_deleted = False
    try:
        feishu_config = FeishuConfig.from_config(config)
        client = FeishuBitableClient(feishu_config)
        if not feishu_config.app_token:
            print("配置检查失败：请填写飞书 Base 链接或 Base App Token。")
            return 1
        if not feishu.get("base_url"):
            feishu["base_url"] = f"https://feishu.cn/base/{feishu_config.app_token}"
        tables = client.list_tables()
        table_id = str(feishu.get("workspace_table_id") or feishu.get("table_id") or "")
        if table_id:
            if any(str(table.get("table_id") or "") == table_id for table in tables):
                client.delete_table(table_id)
                workspace_deleted = True
            else:
                logging.warning("configured workspace %s was already absent; continuing reset recovery", table_id)
        else:
            matches = [table for table in tables if table.get("name") == desired_workspace().table_name]
            if len(matches) != 1:
                if matches:
                    print(f"reset 失败：未能唯一定位“{desired_workspace().table_name}”数据表（找到 {len(matches)} 个）。")
                    return 1
                logging.info("no managed workspace found; continuing local reset recovery")
            else:
                table_id = str(matches[0].get("table_id") or "")
                if not table_id:
                    print("reset 失败：飞书返回的数据表缺少 table_id。")
                    return 1
                client.delete_table(table_id)
                workspace_deleted = True
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="Feishu workspace reset failed",
            error=_cli_error_spec("reset"),
        )
        return 1

    config["feishu"]["workspace_table_id"] = ""
    config["feishu"]["table_id"] = ""
    config["feishu"]["workspace_schema_version"] = ""
    save_config(config, config_path)
    try:
        restore_seed_database(db_path, overwrite=True)
    except (SeedDatabaseError, OSError) as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="seed database restore failed after workspace deletion",
            error=_cli_error_spec("reset"),
        )
        return 1
    action = "已删除当前飞书工作台" if workspace_deleted else "未发现需要删除的受管工作台"
    print(f"{action}，并从 seed 恢复本地岗位库，正在重新初始化。")
    return _run_init(
        config,
        db_path,
        config_path,
        output_path,
        assume_yes=True,
        seeded_from_reset=True,
    )


def _run_daily(config: dict, db_path: str, skip_feishu: bool = False, reporter: RunReporter | None = None) -> int:
    workflow_config = config
    if skip_feishu:
        workflow_config = deepcopy(config)
        workflow_config["feishu"] = {}
    result = run_daily_workflow(
        workflow_config,
        db_path,
        reporter=reporter or RunReporter(),
    )
    run_guard_error = next((error for error in result.errors if error.stage == "run_guard"), None)
    if run_guard_error:
        print(f"daily result: status=already_running message={run_guard_error.message}")
        return result.exit_code
    print(_format_daily_result(result))
    if result.fetched_count == 0:
        print("提示：本次没有获取到新页面岗位；如连续发生，请运行 check 并查看日志中的页面解析或网络错误。")
    _print_daily_recovery_advice(result)
    return result.exit_code


def _run_rematch(
    config: dict,
    db_path: str,
    recommendation_date: str | None = None,
    *,
    skip_feishu: bool = False,
    skip_enrich_official: bool = False,
    reporter: RunReporter | None = None,
) -> int:
    reporter = reporter or RunReporter()
    repo = DatabaseBootstrapService(db_path).initialize()
    enrich_summary = None
    sync_summary = SyncSummary()
    pull_summary = PullSummary()
    if not skip_feishu and _feishu_is_configured(config):
        try:
            logging.info("Pulling latest user states from Feishu before rematch sync...")
            pull_client = FeishuBitableClient(FeishuConfig.from_config(config))
            pull_summary = _pull_summary(pull_user_states_from_feishu(repo, pull_client))
        except Exception as exc:
            _report_cli_exception(
                config,
                exc,
                log_message="Failed to pull latest user states from Feishu",
                error=_cli_error_spec("rematch"),
            )
            pull_summary = PullSummary(failed=1)

    if _pull_has_anomalies(pull_summary):
        print(_format_pull_summary("rematch", pull_summary))
        _print_recovery_advice(pull_summary, sync_summary)
        return 1

    reporter.stage("rematch", 1, 2, "按当前偏好重新匹配岗位")
    summary = rematch_existing_jobs(repo, config, recommendation_date)
    reporter.stage("rematch", 1, 2, "按当前偏好重新匹配岗位", "done", f"推荐 {summary.recommended_items} 条")
    if not skip_feishu and _feishu_is_configured(config):
        if not skip_enrich_official:
            enrich_summary = enrich_official_urls(repo, OfficialUrlFinder(), only_recommended=True)
        sync_summary = _sync_feishu(repo, config, repo.list_feishu_reconciliation_rows())
    repo.record_scan_run(
        {
            "run_type": "rematch",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "partial" if sync_summary.failed else "success",
            "pages_scanned": 0,
            "items_seen": summary.items_seen,
            "new_items": summary.new_items,
            "updated_items": summary.updated_items,
            "error_message": f"飞书同步失败 {sync_summary.failed} 条" if sync_summary.failed else None,
        }
    )
    logging.info(
        "rematch finished: seen=%s recommended=%s official_seen=%s official_updated=%s feishu_created=%s feishu_updated=%s feishu_failed=%s",
        summary.items_seen,
        summary.recommended_items,
        enrich_summary.items_seen if enrich_summary else 0,
        enrich_summary.updated_items if enrich_summary else 0,
        sync_summary.created,
        sync_summary.updated,
        sync_summary.failed,
    )
    print(_format_run_summary("rematch", summary, enrich_summary, pull_summary, sync_summary))
    reporter.finish(RunReport("rematch", "partial" if sync_summary.failed else "success", items_seen=summary.items_seen, recommended_items=summary.recommended_items, current_workspace_items=len(repo.list_feishu_sync_candidates()), feishu_created=sync_summary.created, feishu_updated=sync_summary.updated, feishu_skipped=sync_summary.skipped, feishu_failed=sync_summary.failed, workspace_url=str(config.get("feishu", {}).get("base_url") or ""), advice="偏好匹配已刷新。"))
    _print_recovery_advice(pull_summary, sync_summary)
    repo.vacuum()
    return 1 if sync_summary.failed else 0


def _run_backfill_details(
    config: dict,
    db_path: str,
    recommendation_date: str | None = None,
    min_raw_text_length: int = 500,
) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    crawler = WonderCVCrawler(config)
    summary = backfill_existing_job_details(
        repo,
        crawler,
        config,
        recommendation_date=recommendation_date,
        min_raw_text_length=min_raw_text_length,
    )
    repo.record_scan_run(
        {
            "run_type": "backfill-details",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "pages_scanned": 0,
            "items_seen": summary.items_seen,
            "new_items": summary.new_items,
            "updated_items": summary.updated_items,
            "error_message": None,
        }
    )
    logging.info("backfill-details finished: seen=%s recommended=%s", summary.items_seen, summary.recommended_items)
    repo.vacuum()
    return 0


def _run_enrich_official_urls(
    config: dict,
    db_path: str,
    *,
    only_recommended: bool = True,
    limit: int | None = None,
) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    finder = OfficialUrlFinder()
    summary = enrich_official_urls(repo, finder, only_recommended=only_recommended, limit=limit)
    repo.record_scan_run(
        {
            "run_type": "enrich-official-urls",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "pages_scanned": 0,
            "items_seen": summary.items_seen,
            "new_items": summary.new_items,
            "updated_items": summary.updated_items,
            "error_message": None,
        }
    )
    logging.info("enrich-official-urls finished: seen=%s updated=%s", summary.items_seen, summary.updated_items)
    repo.vacuum()
    return 0


def _run_pull(config: dict, db_path: str, reporter: RunReporter | None = None) -> int:
    reporter = reporter or RunReporter()
    try:
        repo = JobRepository(db_path)
        repo.init_schema()
        client = FeishuBitableClient(FeishuConfig.from_config(config))
        pull_summary = _pull_summary(pull_user_states_from_feishu(repo, client))
        repo.record_scan_run(
            {
                "run_type": "pull",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "status": "partial" if _pull_has_anomalies(pull_summary) else "success",
                "pages_scanned": 0,
                "items_seen": 0,
                "new_items": 0,
                "updated_items": pull_summary.updated,
                "error_message": _run_error_message(pull_summary, SyncSummary()),
            }
        )
        logging.info(
            "pull finished: updated=%d skipped=%d unknown=%d",
            pull_summary.updated,
            pull_summary.skipped,
            pull_summary.unknown,
        )
        print(_format_pull_summary("pull", pull_summary))
        reporter.finish(RunReport("pull", "partial" if _pull_has_anomalies(pull_summary) else "success", feishu_updated=pull_summary.updated, advice="已回收飞书中的求职状态。"))
        _print_recovery_advice(pull_summary, SyncSummary())
        return 1 if _pull_has_anomalies(pull_summary) else 0
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="Failed to pull from Feishu",
            error=_cli_error_spec("pull"),
        )
        return 1


def _run_check(config: dict, db_path: str, reporter: RunReporter | None = None) -> int:
    """Report Feishu/local reconciliation facts without modifying either side."""
    reporter = reporter or RunReporter()
    try:
        repo = JobRepository(db_path)
        repo.init_schema()
        client = FeishuBitableClient(FeishuConfig.from_config(config))
        report = audit_feishu_records(repo, client.list_all_records())
    except Exception as exc:
        _report_cli_exception(
            config,
            exc,
            log_message="Failed to audit Feishu records",
            error=_cli_error_spec("check"),
        )
        return 1
    print(
        "check summary: "
        f"local_job_count={report.local_job_count} remote_record_count={report.remote_record_count} "
        f"only_local={len(report.only_local_job_ids)} only_remote={len(report.only_remote_record_ids)} "
        f"duplicates={len(report.duplicate_job_ids)} blank={len(report.blank_record_ids)} "
        f"unmatched={len(report.unmatched_record_ids)} unknown_statuses={len(report.unknown_statuses)}"
    )
    has_anomalies = bool(
        report.only_remote_record_ids
        or report.duplicate_job_ids
        or report.blank_record_ids
        or report.unmatched_record_ids
        or report.unknown_statuses
    )
    if has_anomalies:
        print("检测到远端异常记录；已保持只读。请先修复重复、空白、未知岗位或非法状态后再同步。")
    reporter.finish(RunReport("check", "partial" if has_anomalies else "success", items_seen=report.local_job_count, current_workspace_items=report.remote_record_count, advice="检测到远端异常记录；已保持只读。" if has_anomalies else "本地与飞书记录健康。"))
    return 1 if has_anomalies else 0


def _run_open_workspace(config: dict) -> int:
    import webbrowser

    url = str(config.get("feishu", {}).get("base_url") or "")
    if not url:
        print("尚未配置飞书 Base 链接；请先运行首次配置。")
        return 1
    webbrowser.open(url)
    print(f"已请求在浏览器中打开飞书工作台：{url}")
    return 0


def _sync_feishu(repo: JobRepository, config: dict, rows: list[dict]) -> SyncSummary:
    # Transitional compatibility for tests and the legacy CLI.  Web routes
    # call the service directly and do not depend on this private adapter.
    return sync_feishu(repo, config, rows, client_factory=FeishuBitableClient)


def _pull_summary(recovery) -> PullSummary:
    return PullSummary(
        updated=int(recovery.updated_count),
        skipped=len(recovery.skipped_record_ids),
        unknown=len(recovery.unknown_statuses),
    )


def _read_only_workspace_preflight(client, config: dict) -> None:
    """Verify every safe read needed before the user approves remote changes."""
    tables = client.list_tables()
    table_id = str(config.get("feishu", {}).get("workspace_table_id") or "")
    if not table_id:
        return
    if not any(str(table.get("table_id") or "") == table_id for table in tables):
        raise RuntimeError("配置中的求职工作台不存在；请检查 Base 链接，或清空 workspace_table_id 后重新初始化")
    client.list_fields(table_id)
    client.list_views(table_id)
    client.list_all_records(table_id)


def _feishu_is_configured(config: dict) -> bool:
    feishu = FeishuConfig.from_config(config)
    has_auth = bool(feishu.tenant_access_token or (feishu.app_id and feishu.app_secret))
    return bool(feishu.app_token and feishu.table_id and has_auth)


def _pull_has_anomalies(summary: PullSummary) -> bool:
    return bool(summary.skipped or summary.unknown or summary.failed)


def _run_error_message(pull_summary: PullSummary, sync_summary: SyncSummary) -> str | None:
    if pull_summary.failed:
        return "飞书用户字段回拉失败"
    if pull_summary.skipped or pull_summary.unknown:
        return f"飞书异常记录 skipped={pull_summary.skipped} unknown={pull_summary.unknown}"
    if sync_summary.failed:
        return f"飞书同步失败 {sync_summary.failed} 条"
    return None


def _format_daily_result(result: DailyWorkflowResult) -> str:
    summary = (
        f"daily result: status={result.status} seen={result.fetched_count} "
        f"new={result.created_count} updated={result.updated_count} "
        f"unchanged={result.unchanged_count} matched={result.matched_count} "
        f"recommended={result.recommended_count} "
        f"pull_updated={result.feishu_pull_updated_count} "
        f"pull_skipped={result.feishu_pull_skipped_count} "
        f"pull_unknown={result.feishu_pull_unknown_count} "
        f"pull_failed={int(result.feishu_pull_attempted and not result.feishu_pull_succeeded)} "
        f"official_updated={result.link_enriched_count} "
        f"feishu_created={result.feishu_created_count} "
        f"feishu_updated={result.feishu_updated_count} "
        f"feishu_skipped={result.feishu_skipped_count} "
        f"feishu_failed={result.feishu_failed_count} "
        f"notification_status={result.notification_status}"
    )
    if result.error_summary:
        summary += f" errors={result.error_summary}"
    return summary


def _print_daily_recovery_advice(result: DailyWorkflowResult) -> None:
    stages = {error.stage for error in result.errors}
    if "feishu_pull" in stages:
        print("恢复建议：检查网络、飞书凭据和异常记录后安全重试；本次未执行飞书同步。")
    elif "feishu_sync" in stages:
        print("恢复建议：远端已有数据未被清空；检查同步错误后重新运行同一命令即可安全重试。")
    elif result.errors:
        first = result.errors[0]
        print(f"恢复建议：阶段 {first.stage} 失败（{first.message}），请检查日志后重试。")


def _format_pull_summary(command: str, summary: PullSummary) -> str:
    status = "partial" if _pull_has_anomalies(summary) else "success"
    return (
        f"{command} result: status={status} pull_updated={summary.updated} "
        f"pull_skipped={summary.skipped} pull_unknown={summary.unknown} pull_failed={summary.failed}"
    )


def _print_recovery_advice(pull_summary: PullSummary, sync_summary: SyncSummary) -> None:
    if pull_summary.failed:
        print("恢复建议：检查网络、飞书凭据和记录读取权限，然后安全重试；本次未执行后续同步。")
    elif pull_summary.skipped or pull_summary.unknown:
        print("恢复建议：先运行 check，修复重复/空白岗位ID或非法求职状态；异常记录未写入本地，后续同步已停止。")
    elif sync_summary.failed:
        print("恢复建议：远端已有数据未被清空；检查同步错误后重新运行同一命令即可安全重试。")


def _format_run_summary(
    command: str,
    summary,
    enrich_summary,
    pull_summary: PullSummary,
    sync_summary: SyncSummary,
    *,
    partial: bool = False,
) -> str:
    status = "partial" if partial or _pull_has_anomalies(pull_summary) or sync_summary.failed else "success"
    return (
        f"{command} result: status={status} seen={summary.items_seen} new={summary.new_items} "
        f"recommended={summary.recommended_items} "
        f"pull_updated={pull_summary.updated} pull_skipped={pull_summary.skipped} "
        f"pull_unknown={pull_summary.unknown} pull_failed={pull_summary.failed} "
        f"official_seen={enrich_summary.items_seen if enrich_summary else 0} "
        f"official_updated={enrich_summary.updated_items if enrich_summary else 0} "
        f"feishu_created={sync_summary.created} feishu_updated={sync_summary.updated} feishu_skipped={sync_summary.skipped} "
        f"feishu_failed={sync_summary.failed}"
    )

