from jobpicky.taxonomy import canonical_role_id, role_groups, role_labels, role_sections


def test_role_taxonomy_uses_stable_ids_and_search_terms():
    sections = role_sections()
    embedded = next(
        option
        for section in sections
        for option in section["options"]
        if option["value"] == "hardware.embedded"
    )

    assert embedded["label"] == "嵌入式开发"
    assert {"单片机", "BSP", "固件"}.issubset(embedded["search_terms"])
    assert canonical_role_id("硬件/嵌入式") == "hardware.embedded"
    assert canonical_role_id("单片机") == "hardware.embedded"


def test_role_taxonomy_covers_common_job_families():
    groups = role_groups()
    labels = role_labels()

    expected = {
        "software.backend",
        "ai.nlp_llm",
        "data.engineering",
        "chip.verification",
        "cloud.devops",
        "mechanical.design",
        "product.manager",
        "sales",
        "finance",
        "medicine.rnd",
        "civil",
        "research",
    }
    assert expected.issubset(groups)
    assert all(labels[role_id] for role_id in expected)
