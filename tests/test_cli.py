from pathlib import Path

from job_monitor.cli import main, _notification_rows
from job_monitor.models import Job
from job_monitor.feishu import FeishuResult
from job_monitor.storage import JobRepository


def test_cli_export_writes_excel_from_existing_database(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    output = tmp_path / "all_jobs.xlsx"
    repo = JobRepository(db_path)
    repo.init_schema()
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:1",
            company="示例公司",
            title="FPGA工程师",
        )
    )

    exit_code = main(["export", "--db", str(db_path), "--output", str(output)])

    assert exit_code == 0
    assert output.exists()


def test_cli_rematch_backfills_recommendations(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite"
    config_path = tmp_path / "config.yaml"
    repo = JobRepository(db_path)
    repo.init_schema()
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:1",
            company="示例公司",
            title="2027届FPGA工程师",
            batch="秋招",
            target_graduate_year="2027届",
        )
    )
    config_path.write_text(
        """
user_profile:
  graduate_years: ["2027届"]
  batches: ["秋招"]
  role_groups: ["硬件/嵌入式"]
system_taxonomy:
  role_groups:
    硬件/嵌入式: ["FPGA"]
""",
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path), "--db", str(db_path), "rematch", "--date", "2026-07-03"])

    assert exit_code == 0
    assert repo.list_recommended_jobs("2026-07-03")[0]["recommend_reason"] == "命中岗位方向：硬件/嵌入式"
def test_cli_enrich_official_urls_runs_on_recommended_jobs(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    config_path = tmp_path / "config.yaml"
    repo = JobRepository(db_path)
    repo.init_schema()
    result = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:1",
            company="TargetCo",
            title="FPGA工程师",
        )
    )
    repo.append_recommendations("2026-07-09", [{"job_id": result.job_id, "recommend_reason": "推荐"}])
    config_path.write_text("crawler: {}\n", encoding="utf-8")

    class Finder:
        def __init__(self, *args, **kwargs):
            pass

        def find_best(self, job: Job) -> str:
            return "https://careers.example.com/target"

    monkeypatch.setattr("job_monitor.cli.OfficialUrlFinder", Finder)

    exit_code = main([
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "enrich-official-urls",
        "--limit",
        "1",
    ])

    assert exit_code == 0
    assert repo.list_all_jobs()[0]["official_url"] == "https://careers.example.com/target"


def test_cli_rematch_enriches_official_urls_and_syncs_feishu(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    config_path = tmp_path / "config.yaml"
    repo = JobRepository(db_path)
    repo.init_schema()
    result = repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:1",
            company="TargetCo",
            title="2027 FPGA engineer",
            batch="fall",
            target_graduate_year="2027",
        )
    )
    repo.mark_sync(result.job_id, "synced", record_id="rec-target")
    config_path.write_text(
        """
user_profile:
  graduate_years: ["2027"]
  batches: ["fall"]
  role_groups: ["hardware"]
  target_cities: []
  must_watch_companies: []
  exclude_role_groups: []
system_taxonomy:
  role_groups:
    hardware: ["FPGA"]
  exclude_role_groups: {}
  generic_role_terms: []
  important_company_types: []
  important_company_marks: []
  company_aliases: {}
feishu:
  bitable_app_token: base
  table_id: tbl
  tenant_access_token: token
""",
        encoding="utf-8",
    )
    captured = {}

    class Finder:
        def __init__(self, *args, **kwargs):
            pass

        def find_best(self, job: Job) -> str:
            return "https://careers.example.com/target"

    class Client:
        def __init__(self, config):
            pass

        def list_all_records(self):
            return [{"record_id": "rec-target", "fields": {"岗位ID": str(result.job_id)}}]

        def batch_create_records(self, records):
            raise AssertionError("create should not be called")

        def batch_update_records(self, records):
            captured["records"] = records
            return FeishuResult(sent=True)

    monkeypatch.setattr("job_monitor.cli.OfficialUrlFinder", Finder)
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)

    exit_code = main(["--config", str(config_path), "--db", str(db_path), "rematch", "--date", "2026-07-09"])

    assert exit_code == 0
    row = repo.list_all_jobs()[0]
    assert row["official_url"] == "https://careers.example.com/target"
    assert row["sync_status"] == "synced"
    assert captured["records"][0]["record_id"] == "rec-target"
    assert captured["records"][0]["fields"]["投递入口"]["link"] == "https://careers.example.com/target"


def test_cli_rematch_no_feishu_skips_enrichment_and_sync(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    config_path = tmp_path / "config.yaml"
    repo = JobRepository(db_path)
    repo.init_schema()
    repo.upsert_job(
        Job(
            source="WonderCV",
            dedupe_key="WonderCV:id:1",
            company="TargetCo",
            title="2027 FPGA engineer",
            batch="fall",
            target_graduate_year="2027",
        )
    )
    config_path.write_text(
        """
user_profile:
  graduate_years: ["2027"]
  batches: ["fall"]
  role_groups: ["hardware"]
  target_cities: []
  must_watch_companies: []
  exclude_role_groups: []
system_taxonomy:
  role_groups:
    hardware: ["FPGA"]
  exclude_role_groups: {}
  generic_role_terms: []
  important_company_types: []
  important_company_marks: []
  company_aliases: {}
""",
        encoding="utf-8",
    )

    class Finder:
        def __init__(self, *args, **kwargs):
            raise AssertionError("official URL enrichment should not run")

    class Client:
        def __init__(self, config):
            raise AssertionError("feishu sync should not run")

    monkeypatch.setattr("job_monitor.cli.OfficialUrlFinder", Finder)
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)

    exit_code = main([
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "rematch",
        "--date",
        "2026-07-09",
        "--no-feishu",
    ])

    assert exit_code == 0
    assert len(repo.list_recommended_jobs("2026-07-09")) == 1
    assert repo.list_all_jobs()[0]["official_url"] is None


def test_cli_daily_enriches_official_urls_before_feishu_sync(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
user_profile:
  graduate_years: ["2027"]
  batches: ["fall"]
  role_groups: ["hardware"]
  target_cities: []
  must_watch_companies: []
  exclude_role_groups: []
system_taxonomy:
  role_groups:
    hardware: ["FPGA"]
  exclude_role_groups: {}
  generic_role_terms: []
  important_company_types: []
  important_company_marks: []
  company_aliases: {}
feishu:
  bitable_app_token: base
  table_id: tbl
  tenant_access_token: token
  webhook_url: https://example.com/hook
""",
        encoding="utf-8",
    )
    captured = {}

    class Crawler:
        def __init__(self, config):
            pass

        def crawl(self, mode, should_stop):
            return type(
                "Crawl",
                (),
                {
                    "jobs": [
                        Job(
                            source="WonderCV",
                            dedupe_key="WonderCV:id:daily",
                            company="DailyCo",
                            title="2027 FPGA engineer",
                            batch="fall",
                            target_graduate_year="2027",
                        )
                    ],
                    "pages_scanned": 1,
                    "error": None,
                },
            )()

    class Finder:
        def __init__(self, *args, **kwargs):
            pass

        def find_best(self, job: Job) -> str:
            return "https://careers.example.com/daily"

    class Client:
        def __init__(self, config):
            pass

        def list_all_records(self):
            return []

        def batch_create_records(self, records):
            captured["create_records"] = records
            return FeishuResult(sent=True, record_ids=["rec-daily"])

        def batch_update_records(self, records):
            raise AssertionError("update should not be called for a new Feishu row")

    class Bot:
        def __init__(self, webhook_url):
            pass

        def send_text(self, text):
            captured["message"] = text
            return FeishuResult(sent=True)

    monkeypatch.setattr("job_monitor.cli.WonderCVCrawler", Crawler)
    monkeypatch.setattr("job_monitor.cli.OfficialUrlFinder", Finder)
    monkeypatch.setattr("job_monitor.cli.FeishuBitableClient", Client)
    monkeypatch.setattr("job_monitor.cli.FeishuBot", Bot)

    exit_code = main(["--config", str(config_path), "--db", str(db_path), "daily"])

    assert exit_code == 0
    repo = JobRepository(db_path)
    row = repo.list_all_jobs()[0]
    assert row["official_url"] == "https://careers.example.com/daily"
    assert row["sync_status"] == "synced"
    assert captured["create_records"][0]["fields"]["投递入口"]["link"] == "https://careers.example.com/daily"


def test_notification_rows_obeys_daily_push_limit_without_limiting_recommendations():
    rows = [
        {"recommendation_status": "推荐", "sync_status": "pending", "job_id": 1},
        {"recommendation_status": "推荐", "sync_status": "pending", "job_id": 2},
        {"recommendation_status": "推荐", "sync_status": "pending", "job_id": 3},
    ]

    limited = _notification_rows(rows, {"user_profile": {"daily_push_limit": 1}})

    assert [row["job_id"] for row in limited] == [1]


def test_cli_pull_command(tmp_path, monkeypatch):
    from unittest.mock import patch
    from job_monitor.cli import main
    db_file = tmp_path / "jobs.sqlite"

    with patch("job_monitor.cli.FeishuBitableClient") as mock_client_cls, \
         patch("job_monitor.cli.pull_user_states_from_feishu") as mock_pull:
        mock_pull.return_value = 5
        code = main(["--db", str(db_file), "pull"])
        assert code == 0
        mock_pull.assert_called_once()

