import pytest

from app.services.generation_provenance import build_generation_provenance


def _plans(*, catalog_version: str = "catalog-v1", rule_version: str = "rules-v1"):
    return [
        {
            "shopQuote": {
                "catalogVersion": catalog_version,
                "ruleVersion": rule_version,
            }
        }
    ]


def test_generation_provenance_is_derived_from_executed_artifacts():
    first = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="actual catalog context",
        plans=_plans(),
    )
    changed_input = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-b"},
        catalog_context="actual catalog context",
        plans=_plans(),
    )
    changed_prompt = build_generation_provenance(
        prompt_snapshot="changed static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="actual catalog context",
        plans=_plans(),
    )
    changed_rules = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="actual catalog context",
        plans=_plans(rule_version="rules-v2"),
    )
    changed_data = build_generation_provenance(
        prompt_snapshot="static prompt contract",
        input_snapshot={"user": "case-a"},
        catalog_context="changed catalog context",
        plans=_plans(catalog_version="catalog-v2"),
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
    assert first["rules_digest"] != changed_rules["rules_digest"]
    assert first["data_digest"] != changed_data["data_digest"]


def test_generation_provenance_rejects_missing_or_inconsistent_quote_versions():
    with pytest.raises(ValueError, match="报价版本"):
        build_generation_provenance(
            prompt_snapshot="prompt",
            input_snapshot={"user": "case-a"},
            catalog_context="catalog",
            plans=[{"shopQuote": {}}],
        )

    with pytest.raises(ValueError, match="同一版本"):
        build_generation_provenance(
            prompt_snapshot="prompt",
            input_snapshot={"user": "case-a"},
            catalog_context="catalog",
            plans=_plans() + _plans(rule_version="rules-v2"),
        )
