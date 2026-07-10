from job_monitor.models import Job
from job_monitor.pipeline import InitSummary, run_init_with_page_batches
from job_monitor.storage import JobRepository


def test_init_pipeline_saves_each_page_batch_incrementally(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite")
    repo.init_schema()
    config = {
        "user_profile": {
            "graduate_years": [],
            "batches": [],
            "role_groups": ["硬件/嵌入式"],
            "target_industries": [],
            "target_cities": [],
            "must_watch_companies": [],
            "exclude_role_groups": [],
        },
        "system_taxonomy": {
            "role_groups": {"硬件/嵌入式": ["FPGA"]},
            "exclude_role_groups": {},
            "generic_role_terms": [],
            "important_company_types": [],
            "important_company_marks": [],
            "company_aliases": {},
        },
    }
    page_batches = [
        [Job(source="WonderCV", dedupe_key="WonderCV:id:1", company="A", title="FPGA", collected_date="2026-07-02")],
        [Job(source="WonderCV", dedupe_key="WonderCV:id:2", company="B", title="FPGA", collected_date="2026-07-01")],
    ]

    summary = run_init_with_page_batches(repo, page_batches, config)

    assert summary == InitSummary(pages_scanned=2, items_seen=2, new_items=2, updated_items=0, relevant_items=2)
    assert repo.count_jobs() == 2
