import os
import pytest

@pytest.fixture(autouse=True, scope="session")
def redirect_logging(tmp_path_factory):
    tmp_log_dir = tmp_path_factory.mktemp("logs")
    os.environ["JOBPICKY_LOG_DIR"] = str(tmp_log_dir)

@pytest.fixture
def mock_config():
    def _make_config(daily_push_limit: int | None = 20) -> dict:
        profile = {
            "graduate_years": ["2027届"],
            "batches": ["秋招"],
            "role_groups": ["硬件/嵌入式"],
            "target_industries": [],
            "target_cities": ["Shanghai"],
            "must_watch_companies": ["TargetCo"],
            "exclude_role_groups": [],
            "recall_mode": "balanced",
        }
        if daily_push_limit is not None:
            profile["daily_push_limit"] = daily_push_limit
        return {
            "profile": {"version": 2},
            "user_profile": profile,
            "system_taxonomy": {
                "role_groups": {"硬件/嵌入式": ["FPGA"]},
                "exclude_role_groups": {},
                "generic_role_terms": ["研发类"],
                "important_company_types": ["上市公司"],
                "important_company_marks": [],
                "company_aliases": {},
            },
        }
    return _make_config
