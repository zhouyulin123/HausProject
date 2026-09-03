from app.services import generation_provenance
from app.services.generation_provenance import (
    GENERATION_PROVENANCE_SCHEMA_VERSION,
    build_generation_provenance,
)


EXPECTED_RULE_ARTIFACT_IDS = [
    "app/agents/design_workflow.py",
    "app/services/catalog_service.py",
    "app/services/generation_scene_service.py",
    "app/services/layout_service.py",
    "app/services/layout_generator.py",
    "app/services/layout_evaluator.py",
    "app/services/layout_repair.py",
    "app/services/scene_geometry.py",
]


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


def test_rule_artifact_snapshot_covers_the_actual_generation_and_layout_chain():
    snapshot = generation_provenance.generation_rule_artifact_snapshot()

    assert GENERATION_PROVENANCE_SCHEMA_VERSION == 3
    assert [item["artifact_id"] for item in snapshot] == EXPECTED_RULE_ARTIFACT_IDS
    assert all(
        set(item) == {"artifact_id", "content_digest"}
        and item["content_digest"].startswith("sha256:")
        for item in snapshot
    )


def test_rules_digest_is_path_independent_and_changes_with_layout_rule_content(
    tmp_path,
    monkeypatch,
):
    first_path = tmp_path / "checkout-a" / "layout_generator.py"
    second_path = tmp_path / "checkout-b" / "layout_generator.py"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_text("RULE = 1\n", encoding="utf-8")
    second_path.write_text("RULE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        generation_provenance,
        "_RULE_ARTIFACTS",
        (("app/services/layout_generator.py", first_path),),
    )
    first = build_generation_provenance(
        prompt_snapshot="prompt",
        input_snapshot={"case": "a"},
        catalog_context="catalog",
    )
    monkeypatch.setattr(
        generation_provenance,
        "_RULE_ARTIFACTS",
        (("app/services/layout_generator.py", second_path),),
    )
    same_content_at_another_path = build_generation_provenance(
        prompt_snapshot="prompt",
        input_snapshot={"case": "a"},
        catalog_context="catalog",
    )
    second_path.write_text("RULE = 2\n", encoding="utf-8")
    changed_layout_rule = build_generation_provenance(
        prompt_snapshot="prompt",
        input_snapshot={"case": "a"},
        catalog_context="catalog",
    )

    assert first["rules_digest"] == same_content_at_another_path["rules_digest"]
    assert first["rules_digest"] != changed_layout_rule["rules_digest"]
