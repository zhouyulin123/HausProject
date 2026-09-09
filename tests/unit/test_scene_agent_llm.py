import pytest

from app.services import llm_service


@pytest.mark.unit
def test_scene_agent_retries_once_when_model_returns_no_operations(monkeypatch):
    responses = iter(
        [
            {"message": "信息不足", "operations": []},
            {
                "message": "已将沙发向左移动 30 厘米",
                "operations": [
                    {
                        "type": "move",
                        "instanceId": "sofa-main",
                        "position": {"x": -0.3, "z": -1},
                    }
                ],
            },
        ]
    )
    calls = []

    def fake_chat_json(system, user, **kwargs):
        calls.append((system, user, kwargs))
        return next(responses)

    monkeypatch.setattr(llm_service, "_chat_json", fake_chat_json)

    result = llm_service.plan_scene_operations(
        instruction="把沙发向左移动30厘米",
        context={
            "scene": {
                "items": [
                    {
                        "instanceId": "sofa-main",
                        "transform": {"position": {"x": 0, "z": -1}},
                    }
                ]
            },
            "catalog": [],
        },
    )

    assert len(calls) == 2
    assert result.operations[0].type == "move"
    assert result.operations[0].position.x == -0.3
    assert "上一次返回了空 operations" in calls[1][1]
