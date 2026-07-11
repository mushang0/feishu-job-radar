from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .alerts import build_daily_message
from .audit import audit_feishu_records
from .config import load_config, save_config, validate_config
from .diagnostics import preflight_check
from .exporters import export_jobs_to_excel
from .feishu import FeishuBitableClient, FeishuBot, FeishuConfig
from .feishu_records import build_create_fields, build_update_fields
from .logging_utils import setup_logging
from .onboarding import InitializationPreview, collect_missing_config, confirm_initialization
from .official_search import OfficialUrlFinder
from .pipeline import backfill_existing_job_details, enrich_official_urls, rematch_existing_jobs, run_daily_with_jobs, run_init_with_page_batches, pull_user_states_from_feishu
from .seed import SeedDatabaseError, find_seed_database, restore_seed_database
from .run_guard import DailyRunGuard, DailyRunInProgress
from .storage import JobRepository
from .wondercv import WonderCVCrawler
from .workspace_provisioner import WorkspaceProvisioner
from .workspace_schema import WORKSPACE_SCHEMA_VERSION, desired_workspace


@dataclass(frozen=True, slots=True)
class SyncSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class PullSummary:
    updated: int = 0
    skipped: int = 0
    unknown: int = 0
    failed: int = 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feishu-job-radar")
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

    args = parser.parse_args(argv)
    db_path = args.command_db or args.db
    config_path = getattr(args, "command_config", None) or args.config
    if args.command == "export":
        return _run_export(db_path, args.output, args.table, args.date)

    import os
    config = load_config(config_path)
    log_name = f"{args.command}-{datetime.now().date().isoformat()}.log"
    log_dir = os.environ.get("JOB_MONITOR_LOG_DIR", "data/logs")
    setup_logging(Path(log_dir) / log_name)

    if args.command == "init":
        return _run_init(config, db_path, config_path, args.output, assume_yes=args.yes)
    if args.command == "reset":
        return _run_reset(config, db_path, config_path, args.output, confirmed=args.yes)
    if args.command == "daily":
        return _run_daily(config, db_path, skip_feishu=args.no_feishu)
    if args.command == "rematch":
        return _run_rematch(
            config,
            db_path,
            args.date,
            skip_feishu=args.no_feishu,
            skip_enrich_official=args.no_enrich_official,
        )
    if args.command == "pull":
        return _run_pull(config, db_path)
    if args.command == "check":
        return _run_check(config, db_path)
    return 2


def _run_export(db_path: str, output_path: str, table: str = "all", export_date: str | None = None) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    if table == "recommended":
        rows = repo.list_recommended_jobs(export_date)
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
) -> int:
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
        logging.error("initial configuration failed: %s", exc)
        print(f"初始化配置失败：{exc}")
        return 1

    try:
        seeded = restore_seed_database(db_path)
    except SeedDatabaseError as exc:
        print(f"seed 数据库初始化失败：{exc}")
        return 1
    except OSError as exc:
        logging.error("seed database initialization failed: %s", exc)
        print(f"seed 数据库初始化失败：{exc}")
        return 1

    repo = JobRepository(db_path)
    repo.init_schema()
    local_preflight = preflight_check(config, db_path)
    if not local_preflight.ok:
        print("运行前检查失败：" + "；".join(local_preflight.errors))
        return 1

    try:
        client = FeishuBitableClient(FeishuConfig.from_config(config))
        client.get_app()
        _read_only_workspace_preflight(client, config)
    except Exception as exc:
        logging.error("Feishu read-only preflight failed: %s", exc)
        print(f"飞书连接检查失败：{exc}")
        return 1

    preview = InitializationPreview(
        base_url=str(config["feishu"]["base_url"]),
        table_name=desired_workspace().table_name,
        pending_candidates=len(repo.list_feishu_sync_candidates()),
    )
    if not confirm_initialization(preview, assume_yes=assume_yes):
        print("已取消初始化，未修改飞书结构。")
        return 0

    try:
        def persist_table_id(table_id: str) -> None:
            config["feishu"]["workspace_table_id"] = table_id
            save_config(config, config_path)

        provisioning = WorkspaceProvisioner(client, desired_workspace()).provision(
            config["feishu"].get("workspace_table_id") or None,
            on_table_created=persist_table_id,
        )
        config["feishu"]["workspace_table_id"] = provisioning.table_id
        config["feishu"]["workspace_schema_version"] = WORKSPACE_SCHEMA_VERSION
        save_config(config, config_path)
    except Exception as exc:
        logging.exception("Feishu workspace provisioning failed")
        print(f"飞书工作台初始化失败：{exc}")
        return 1

    started_at = datetime.now().isoformat(timespec="seconds")
    summary = rematch_existing_jobs(repo, config)

    sync_summary = _sync_feishu(repo, config, repo.list_feishu_reconciliation_rows())
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
    seed_origin = seeded or seeded_from_reset
    source_label = "已从 seed 恢复本地岗位库" if seed_origin else "使用已有本地岗位库"
    print(f"初始化数据：{source_label}；已重新匹配，不执行首次全量抓取。")
    print(_format_run_summary("init", summary, None, PullSummary(), sync_summary))
    if summary.items_seen == 0:
        print("提示：本地岗位库为空；请确认运行数据库未被错误替换，或运行 daily 获取新增岗位。")
    print(f"飞书工作台：{provisioning.workspace_url}")
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
        print(f"reset 失败：{exc}")
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
        logging.exception("Feishu workspace reset failed")
        print(f"飞书工作台删除失败，未修改本地配置：{exc}")
        return 1

    config["feishu"]["workspace_table_id"] = ""
    config["feishu"]["table_id"] = ""
    config["feishu"]["workspace_schema_version"] = ""
    save_config(config, config_path)
    try:
        restore_seed_database(db_path, overwrite=True)
    except (SeedDatabaseError, OSError) as exc:
        logging.exception("seed database restore failed after workspace deletion")
        print(f"seed 数据库恢复失败：{exc}。已清除失效工作台 ID，请在占用解除后直接重试 reset --yes。")
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


def _run_daily(config: dict, db_path: str, skip_feishu: bool = False) -> int:
    try:
        with DailyRunGuard(db_path) as guard:
            return _run_daily_guarded(config, db_path, skip_feishu, guard.cancelled.is_set)
    except DailyRunInProgress as exc:
        print(f"daily result: status=already_running message={exc}")
        return 1


def _run_daily_guarded(config: dict, db_path: str, skip_feishu: bool, cancel_check) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    crawler = WonderCVCrawler(config)
    crawler.cancel_check = cancel_check
    last_run_date = repo.get_last_successful_run_date("daily")

    def should_stop(page_jobs) -> bool:
        if not page_jobs:
            return True
        # 1. Stop if all jobs on this page already exist in the database
        all_exist = True
        for job in page_jobs:
            if not repo.job_exists(job.dedupe_key):
                all_exist = False
                break
        if all_exist:
            logging.info("Dynamic stop triggered: all jobs on the current page already exist in the database.")
            return True

        # 2. Stop if all jobs on the page are older than the last successful daily run date
        if last_run_date:
            all_older = True
            for job in page_jobs:
                if job.collected_date and job.collected_date >= last_run_date:
                    all_older = False
                    break
            if all_older:
                logging.info(f"Dynamic stop triggered: all jobs on the page are older than the last successful run date ({last_run_date}).")
                return True

        return False

    crawl = crawler.crawl(mode="daily", should_stop=should_stop)
    if getattr(crawl, "interrupted", False) or cancel_check():
        repo.record_scan_run(
            {"run_type": "daily", "started_at": datetime.now().isoformat(timespec="seconds"),
             "finished_at": datetime.now().isoformat(timespec="seconds"), "status": "interrupted",
             "pages_scanned": crawl.pages_scanned, "items_seen": 0, "new_items": 0,
             "updated_items": 0, "error_message": crawl.error}
        )
        print("daily result: status=interrupted message=启动器已结束，已停止扫描且未同步数据")
        return 1
    summary = run_daily_with_jobs(repo, crawl.jobs, config)
    enrich_summary = None
    sync_summary = SyncSummary()
    pull_summary = PullSummary()
    rows = repo.list_all_jobs()
    recommended_rows = _notification_rows(rows, config)

    if not skip_feishu and _feishu_is_configured(config):
        try:
            logging.info("Pulling latest user states from Feishu before sync...")
            pull_client = FeishuBitableClient(FeishuConfig.from_config(config))
            pull_summary = _pull_summary(pull_user_states_from_feishu(repo, pull_client))
        except Exception as exc:
            logging.warning("Failed to pull latest user states from Feishu: %s", exc)

        if not _pull_has_anomalies(pull_summary):
            enrich_summary = enrich_official_urls(repo, OfficialUrlFinder(), only_recommended=True)
            rows = repo.list_feishu_sync_candidates()
            sync_summary = _sync_feishu(repo, config, rows)
        else:
            logging.error("Feishu sync blocked because user-state reconciliation was not clean")
        message = build_daily_message(summary.new_items, recommended_rows, crawl.error)
        bot = FeishuBot(FeishuConfig.from_config(config).webhook_url)
        bot_result = bot.send_text(message)
        if not bot_result.sent:
            logging.info("feishu bot skipped: %s", bot_result.error)

    repo.record_scan_run(
        {
            "run_type": "daily",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "partial" if crawl.error or sync_summary.failed or _pull_has_anomalies(pull_summary) else "success",
            "pages_scanned": crawl.pages_scanned,
            "items_seen": summary.items_seen,
            "new_items": summary.new_items,
            "updated_items": summary.updated_items,
            "error_message": crawl.error or _run_error_message(pull_summary, sync_summary),
        }
    )
    logging.info(
        "daily finished: seen=%s new=%s recommended=%s official_seen=%s official_updated=%s feishu_created=%s feishu_updated=%s feishu_failed=%s",
        summary.items_seen,
        summary.new_items,
        summary.recommended_items,
        enrich_summary.items_seen if enrich_summary else 0,
        enrich_summary.updated_items if enrich_summary else 0,
        sync_summary.created,
        sync_summary.updated,
        sync_summary.failed,
    )
    print(_format_run_summary("daily", summary, enrich_summary, pull_summary, sync_summary, partial=bool(crawl.error)))
    if summary.items_seen == 0:
        print("提示：本次没有获取到新页面岗位；如连续发生，请运行 check 并查看日志中的页面解析或网络错误。")
    _print_recovery_advice(pull_summary, sync_summary)
    repo.vacuum()
    return 1 if (crawl.error and not crawl.jobs) or sync_summary.failed or _pull_has_anomalies(pull_summary) else 0


def _run_rematch(
    config: dict,
    db_path: str,
    recommendation_date: str | None = None,
    *,
    skip_feishu: bool = False,
    skip_enrich_official: bool = False,
) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    enrich_summary = None
    sync_summary = SyncSummary()
    pull_summary = PullSummary()
    if not skip_feishu and _feishu_is_configured(config):
        try:
            logging.info("Pulling latest user states from Feishu before rematch sync...")
            pull_client = FeishuBitableClient(FeishuConfig.from_config(config))
            pull_summary = _pull_summary(pull_user_states_from_feishu(repo, pull_client))
        except Exception as exc:
            logging.exception("Failed to pull latest user states from Feishu")
            pull_summary = PullSummary(failed=1)

    if _pull_has_anomalies(pull_summary):
        print(_format_pull_summary("rematch", pull_summary))
        _print_recovery_advice(pull_summary, sync_summary)
        return 1

    summary = rematch_existing_jobs(repo, config, recommendation_date)
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


def _run_pull(config: dict, db_path: str) -> int:
    repo = JobRepository(db_path)
    repo.init_schema()
    client = FeishuBitableClient(FeishuConfig.from_config(config))
    try:
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
        _print_recovery_advice(pull_summary, SyncSummary())
        return 1 if _pull_has_anomalies(pull_summary) else 0
    except Exception as exc:
        logging.exception("Failed to pull from Feishu")
        print(f"Error pulling from Feishu: {exc}")
        return 1


def _run_check(config: dict, db_path: str) -> int:
    """Report Feishu/local reconciliation facts without modifying either side."""
    repo = JobRepository(db_path)
    repo.init_schema()
    client = FeishuBitableClient(FeishuConfig.from_config(config))
    try:
        report = audit_feishu_records(repo, client.list_all_records())
    except Exception as exc:
        logging.exception("Failed to audit Feishu records")
        print(f"Error checking Feishu: {exc}")
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
    return 1 if has_anomalies else 0


def _sync_feishu(repo: JobRepository, config: dict, rows: list[dict]) -> SyncSummary:
    feishu_config = FeishuConfig.from_config(config)
    has_auth = bool(feishu_config.tenant_access_token or (feishu_config.app_id and feishu_config.app_secret))
    if not (feishu_config.app_token and feishu_config.table_id and has_auth):
        logging.info("feishu sync skipped: workspace credentials are not configured")
        return SyncSummary(skipped=len(rows))
    client = FeishuBitableClient(feishu_config)
    tracked_statuses = {"收藏", "已投递", "笔试中", "面试中", "Offer", "已结束"}
    to_create: list[dict] = []
    to_update: list[tuple[dict, str]] = []
    created = 0
    updated = 0
    failed = 0
    skipped = 0

    for row in rows:
        job_id = int(row.get("job_id", row.get("id")))
        remote_record_id = str(row.get("feishu_record_id") or "")
        should_exist = bool(row.get("recommendation_active")) or row.get("user_status") in tracked_statuses
        if remote_record_id:
            if row.get("sync_status") in (None, "pending", "pending_update", "failed"):
                to_update.append((row, remote_record_id))
            else:
                skipped += 1
            continue
        if should_exist:
            to_create.append(row)
        else:
            repo.mark_sync(job_id, "synced", record_id=None)
            skipped += 1

    if to_create:
        create_result = client.batch_create_records([{"fields": build_create_fields(row)} for row in to_create])
        if not create_result.sent:
            for row in to_create:
                job_id = int(row.get("job_id", row.get("id")))
                repo.mark_sync(job_id, "failed", error=getattr(create_result, "error", None))
                failed += 1
            logging.info("feishu bitable create failed: %s", getattr(create_result, "error", None))
        else:
            returned_ids = list(getattr(create_result, "record_ids", []) or [])
            for row, record_id in zip(to_create, returned_ids):
                job_id = int(row.get("job_id", row.get("id")))
                if record_id:
                    repo.mark_sync(job_id, "synced", record_id=record_id)
                    created += 1
                else:
                    repo.mark_sync(job_id, "failed", error="飞书创建成功但回读不到 record_id")
                    failed += 1

    if to_update:
        update_records = []
        for row, record_id in to_update:
            update_records.append({"record_id": record_id, "fields": build_update_fields(row)})
        update_result = client.batch_update_records(update_records)
        if not update_result.sent:
            for row, record_id in to_update:
                repo.mark_sync(
                    int(row.get("job_id", row.get("id"))),
                    "failed",
                    record_id=record_id,
                    error=getattr(update_result, "error", None),
                )
            failed += len(to_update)
            logging.info("feishu bitable update skipped or failed: %s", getattr(update_result, "error", None))
            return SyncSummary(created=created, updated=updated, skipped=skipped, failed=failed)
        for row, record_id in to_update:
            repo.mark_sync(int(row.get("job_id", row.get("id"))), "synced", record_id=record_id)
            updated += 1
    return SyncSummary(created=created, updated=updated, skipped=skipped, failed=failed)


def _notification_rows(rows: list[dict], config: dict) -> list[dict]:
    recommended_rows = [
        row for row in rows
        if row.get("recommendation_status") == "推荐"
        and (
            not row.get("feishu_record_id")
            or row.get("sync_status") in ("pending", "failed")
        )
    ]
    limit = _notification_limit(config)
    if limit is None:
        return recommended_rows
    return recommended_rows[:limit]


def _notification_limit(config: dict) -> int | None:
    value = config.get("user_profile", {}).get("daily_push_limit")
    if value in (None, "", "不限制", "unlimited"):
        return None
    return max(int(value), 0)


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

