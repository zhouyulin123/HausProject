import json
from types import SimpleNamespace

import pytest

from app.services import llm_service


@pytest.mark.unit
def test_analyze_room_model_allows_large_structured_output(monkeypatch):
    payload = {
        "schemaVersion": "1.0",
        "imageKind": "floor_plan",
        "spaceType": "全屋",
        "roomCount": "一室一厅",
        "rooms": [
            {
                "id": "living-room",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 1.0, "z": 0.0},
                    {"x": 1.0, "z": 1.0},
                    {"x": 0.0, "z": 1.0},
                ],
                "confidence": 0.8,
            }
        ],
        "confidence": 0.8,
    }
    captured_request = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured_request.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(payload))
                    )
                ]
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(llm_service, "get_vl_client", lambda: fake_client)

    result = llm_service.analyze_room_model(b"png-content", "floor-plan.png")

    assert captured_request["max_tokens"] == 10_000
    assert result is not None
    assert result["rooms"][0]["name"] == "客厅"
