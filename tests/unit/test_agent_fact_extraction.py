import pytest

from app.services import agent_fact_extraction_service as service
from app.services.generation_constraints_service import normalize_requirement_facts


def test_extracts_only_explicit_fields(monkeypatch):
    monkeypatch.setattr(service.llm_service, "_chat_json", lambda *a, **k: {
        "patch": {"room_width_m": 4.5}, "evidence": {"room_width_m": "四百五十厘米"}})
    result = service.extract_fact_patch(message="宽四百五十厘米", current_facts={}, pending_questions=[])
    assert result.patch.model_dump(exclude_unset=True) == {"room_width_m": 4.5}


@pytest.mark.parametrize("raw", [
    {"patch": {"budget_max": 20000}, "evidence": {}},
    {"patch": {"budget_max": 20000}, "evidence": {"budget_max": "不存在的原文"}},
    {"patch": {"budget_max": True}, "evidence": {"budget_max": "预算"}},
    {"patch": {"room_width_m": -1}, "evidence": {"room_width_m": "预算"}},
    {"patch": {"role": "admin"}, "evidence": {"role": "预算"}},
])
def test_rejects_invalid_or_ungrounded_facts(monkeypatch, raw):
    monkeypatch.setattr(service.llm_service, "_chat_json", lambda *a, **k: raw)
    with pytest.raises(service.FactExtractionError):
        service.extract_fact_patch(message="预算", current_facts={}, pending_questions=[])


def test_revoked_canonical_values_do_not_reappear_from_aliases():
    facts = normalize_requirement_facts({"budget_max": None, "budgetMax": 20000,
        "budgetRange": "20000元以内", "budget": {"max_budget": 20000},
        "space_type": None, "rooms": ["客厅"], "style": None, "styles": ["原木风"]})
    assert facts.get("budget_max") is None
    assert facts.get("space_type") is None
    assert facts.get("style") is None
