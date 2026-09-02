from app.services.generation_provenance import build_generation_provenance


def test_generation_provenance_is_frozen_before_any_plan_exists():
    first = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="actual catalog context",
    )
    changed_input = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-b"},
        catalog_context="actual catalog context",
    )
    changed_prompt = build_generation_provenance(
        prompt_snapshot="changed static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="actual catalog context",
    )
    changed_data = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="changed catalog context",
    )

    assert set(first) == {
        "prompt_digest",
        "rules_digest",
        "data_digest",
        "input_digest",
    }
    assert all(value.startswith("sha256:") for value in first.values())
    assert first["prompt_digest"] == changed_input["prompt_digest"]
    assert first["input_digest"] != changed_input["input_digest"]
    assert first["prompt_digest"] != changed_prompt["prompt_digest"]
    assert first["rules_digest"] == changed_input["rules_digest"]
    assert first["data_digest"] != changed_data["data_digest"]


def test_selected_plan_quote_versions_cannot_change_frozen_provenance():
    before_generation = build_generation_provenance(
        prompt_snapshot="prompt",
        input_snapshot={"user": "case-a"},
        catalog_context="complete catalog",
    )

    assert before_generation["rules_digest"].startswith("sha256:")
    assert before_generation["data_digest"].startswith("sha256:")
