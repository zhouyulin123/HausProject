from copy import deepcopy

import pytest

from app.db.models import DesignTask
from app.services import agent_fact_extraction_service as extraction
from tests.integration.test_design_agent_api import agent_api_context  # noqa: F401


def test_chat_patch_persists_replays_and_revokes(agent_api_context, monkeypatch):  # noqa: F811
    client, factory, owner, _, task_id = agent_api_context
    calls = []
    patches = [
        {"budget_max": 20000, "room_width_m": 4.2, "ceiling_height_m": 2.8},
        {"budget_max": None},
        {"room_width_m": 4.5},
    ]
    def extract(**kwargs):
        calls.append(deepcopy(kwargs))
        patch = patches[len(calls) - 1]
        return extraction.FactExtraction(patch=patch, evidence={k: kwargs["message"] for k in patch})
    monkeypatch.setattr(extraction, "extract_fact_patch", extract)
    headers = {"X-Session-ID": owner}
    messages = ["预算两万，宽4.2米，层高2.8米", "预算先撤回", "宽改成450厘米"]
    for index, message in enumerate(messages):
        body = {"client_turn_id": f"chat-facts-{index}", "message": message}
        response = client.post(f"/api/design/tasks/{task_id}/agent-turns", headers=headers, json=body)
        assert response.status_code == 200
        value = response.json()
        assert value["status"] == "waiting_user"
        replay = client.post(f"/api/design/tasks/{task_id}/agent-turns", headers=headers, json=body)
        assert replay.json() == value
        assert len(calls) == index + 1
    assert value["state"]["facts"]["room_width_m"] == 4.5
    assert value["state"]["facts"].get("budget_max") is None
    assert value["state"]["facts"]["ceiling_height_m"] == 2.8
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.budget_max is None
        assert task.confirmed_requirement_json["room_width_m"] == 4.5
        assert task.confirmed_requirement_json["budget_max"] is None


@pytest.mark.parametrize("failure", ["invalid_evidence", "provider_error"])
def test_fact_failure_preserves_confirmed_requirement(agent_api_context, monkeypatch, failure):  # noqa: F811
    client, factory, owner, _, task_id = agent_api_context
    with factory() as db:
        task = db.get(DesignTask, task_id)
        task.budget_max = 18000
        task.confirmed_requirement_json = {"space_type": "客厅", "budget_max": 18000}
        db.commit()

    def extract(**kwargs):
        if failure == "provider_error":
            raise RuntimeError("isolated provider failure")
        raise extraction.FactExtractionError("invalid evidence")

    monkeypatch.setattr(extraction, "extract_fact_patch", extract)
    response = client.post(f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner},
        json={"client_turn_id": f"failed-facts-{failure}", "message": "预算改成两万元"})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    with factory() as db:
        task = db.get(DesignTask, task_id)
        assert task.budget_max == 18000
        assert task.confirmed_requirement_json["budget_max"] == 18000


def test_explicit_form_answer_takes_precedence_over_model_patch(agent_api_context, monkeypatch):  # noqa: F811
    client, _, owner, _, task_id = agent_api_context
    monkeypatch.setattr(extraction, "extract_fact_patch", lambda **kwargs:
        extraction.FactExtraction(patch={"budget_max": 20000}, evidence={"budget_max": "两万元"}))
    response = client.post(f"/api/design/tasks/{task_id}/agent-turns",
        headers={"X-Session-ID": owner}, json={"client_turn_id": "explicit-facts",
            "message": "预算两万元", "answers": {"budget_max": 16000}})
    assert response.status_code == 200
    assert response.json()["state"]["facts"]["budget_max"] == 16000
