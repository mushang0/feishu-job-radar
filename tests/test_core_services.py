import ast
from pathlib import Path
from types import SimpleNamespace

from jobpicky.core import (
    DatabaseBootstrapService,
    DailyUpdateService,
    JobIngestionService,
    JobQueryService,
    MatchingService,
    RecommendationService,
    inspect_local_database,
)
from jobpicky.models import Job
from jobpicky.storage import JobRepository


def _services(tmp_path: Path, config: dict):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    return repo, JobIngestionService(repo, config), MatchingService(repo, config), RecommendationService(repo)


def test_bootstrap_copies_seed_into_runtime_database(tmp_path: Path):
    target = tmp_path / "profile" / "jobs.sqlite"
    repo = DatabaseBootstrapService(target).initialize()
    assert target.exists()
    assert repo.count_jobs() == 747


def test_bootstrap_replaces_empty_schema_but_preserves_valid_database(tmp_path: Path):
    target = tmp_path / "profile" / "jobs.sqlite"
    empty = JobRepository(target)
    empty.init_schema()
    assert inspect_local_database(target).status == "empty_schema"

    repo = DatabaseBootstrapService(target).initialize()
    assert repo.count_jobs() == 747
    assert inspect_local_database(target).status == "valid"

    repo.upsert_job(Job(dedupe_key="local:real", company="Local", title="Real job"))
    DatabaseBootstrapService(target).initialize()
    assert JobRepository(target).count_jobs() == 748


def test_ingestion_classifies_new_changed_and_unchanged_and_protects_detail(tmp_path: Path, mock_config):
    repo, ingestion, _, _ = _services(tmp_path, mock_config())
    ready = Job(source_job_id="1", company="TargetCo", title="FPGA", raw_text="full detail", parse_status="detail_ready")
    first = ingestion.ingest([ready])
    unchanged = ingestion.ingest([ready])
    failed_retry = ingestion.ingest([
        Job(source_job_id="1", company="TargetCo", title="list card", raw_text="short", parse_status="detail_failed")
    ])

    assert (first.new_items, first.updated_items) == (1, 0)
    assert (unchanged.new_items, unchanged.updated_items) == (0, 0)
    assert (failed_retry.new_items, failed_retry.updated_items) == (0, 0)
    saved = repo.list_stored_jobs()[0]
    assert saved["title"] == "FPGA"
    assert saved["raw_text"] == "full detail"
    assert saved["parse_status"] == "detail_ready"


def test_matching_specific_jobs_and_full_rematch_rebuild_recommendations(tmp_path: Path, mock_config):
    repo, ingestion, matching, recommendations = _services(tmp_path, mock_config())
    inserted = ingestion.ingest([
        Job(source_job_id="push", company="TargetCo", title="普通岗位", batch="秋招"),
        Job(source_job_id="skip", company="OtherCo", title="普通岗位", batch="秋招"),
        Job(source_job_id="unfinished", company="TargetCo", title="FPGA", parse_status="detail_failed"),
    ])
    selected = matching.match_job_ids([inserted.items[0].job_id])
    assert selected.matched_items == 1
    assert selected.relevant_items == 1

    repo.append_recommendations("2026-07-01", [{"job_id": inserted.items[1].job_id, "recommend_reason": "stale"}])
    full = matching.rematch_all()
    count = recommendations.rebuild_all(full.matches, "2026-07-02")
    assert full.matched_items == 2
    assert count == 1
    assert [row["job_id"] for row in repo.list_recommended_jobs()] == [inserted.items[0].job_id]


def test_daily_append_keeps_previous_recommendations(tmp_path: Path, mock_config):
    repo, ingestion, matching, recommendations = _services(tmp_path, mock_config())
    first = ingestion.ingest([Job(source_job_id="1", company="TargetCo", title="普通岗位", batch="秋招")])
    recommendations.append_daily(matching.match_ingested(first.changed_items).matches, "2026-07-01")
    second = ingestion.ingest([Job(source_job_id="2", company="TargetCo", title="普通岗位", batch="秋招")])
    recommendations.append_daily(matching.match_ingested(second.changed_items).matches, "2026-07-02")
    assert {row["job_id"] for row in repo.list_recommended_jobs()} == {first.items[0].job_id, second.items[0].job_id}


def test_daily_update_matches_only_new_or_changed_and_needs_no_feishu(tmp_path: Path, mock_config):
    config = mock_config()
    repo, ingestion, matching, recommendations = _services(tmp_path, config)
    jobs = [Job(source_job_id="1", company="TargetCo", title="普通岗位", batch="秋招")]
    crawler = SimpleNamespace(crawl=lambda mode: SimpleNamespace(jobs=jobs, pages_scanned=1))
    service = DailyUpdateService(crawler, ingestion, matching, recommendations)
    first = service.run("2026-07-01")
    second = service.run("2026-07-02")
    assert (first.new_items, first.matched_items, first.recommended_items) == (1, 1, 1)
    assert (second.new_items, second.updated_items, second.matched_items, second.recommended_items) == (0, 0, 0, 0)
    assert JobQueryService(repo).stats() == {"jobs": 1, "recommendations": 1}


def test_core_modules_do_not_import_transport_or_feishu_modules():
    core_dir = Path(__file__).parents[1] / "src" / "jobpicky" / "core"
    forbidden = {"jobpicky.feishu", "jobpicky.audit", "jobpicky.cli", "jobpicky.web"}
    for path in core_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(name in forbidden or name.startswith(tuple(f"{item}." for item in forbidden)) for name in imports)
