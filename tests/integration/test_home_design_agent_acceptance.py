"""独立验证模型建议在损坏历史与过期运行下的失败关闭。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, delete

from app.db.models import HomeDesignAgentTurn, HomeDesignVersion, AnonymousSessionTask
from app.services import llm_service
from tests.integration.test_home_design_agent_api import context, turn  # noqa: F401
from tests.integration.test_home_design_api import context as home_context  # noqa: F401
from tests.integration.test_spatial_api import context as spatial_context  # noqa: F401


@pytest.mark.parametrize("corruption", ["missing", "invalid_json"])
def test_bad_current_version_is_controlled_before_model(context, corruption):  # noqa: F811
    client, url, headers, _, calls, _, _, factory = context
    with factory() as db:
        row = db.scalar(select(HomeDesignVersion))
        if corruption == "missing":
            db.delete(row)
        else:
            row.document_json = {"broken": True}
        db.commit()
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code in (409, 422)
    assert not calls


def test_corruption_during_model_closes_running_reservation(context, monkeypatch):  # noqa: F811
    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def planner(**kwargs):
        with factory() as db:
            row = db.scalar(select(HomeDesignVersion))
            row.document_json = {"broken": True}
            db.commit()
        return original(**kwargs)

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code in (409, 422)
    with factory() as db:
        assert db.scalar(select(HomeDesignAgentTurn)).status == "failed"


def test_expired_running_turn_cannot_become_success_on_late_completion(
    context, monkeypatch  # noqa: F811
):
    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def planner(**kwargs):
        with factory() as db:
            row = db.scalar(select(HomeDesignAgentTurn))
            row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
            db.commit()
        replay = client.post(url, headers=headers, json=turn())
        assert replay.status_code == 409
        assert replay.json()["detail"]["code"] == "home_agent_expired"
        return original(**kwargs)

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "home_agent_expired"


def test_revoked_ownership_discards_candidate_and_closes_turn(context, monkeypatch):  # noqa: F811
    client, url, headers, _, _, _, _, factory = context
    original = llm_service.plan_home_design

    def planner(**kwargs):
        with factory() as db:
            db.execute(delete(AnonymousSessionTask))
            db.commit()
        return original(**kwargs)

    monkeypatch.setattr(llm_service, "plan_home_design", planner)
    result = client.post(url, headers=headers, json=turn())
    assert result.status_code == 404
    with factory() as db:
        row = db.scalar(select(HomeDesignAgentTurn))
        assert row.status == "failed"
        assert row.response_json is None


def test_rate_limit_is_persisted_and_replay_does_not_call_model(context, monkeypatch):  # noqa: F811
    from app.services.home_design_agent_service import open_geometry_rate_limiter

    client, url, headers, _, calls, _, _, _ = context
    monkeypatch.setattr(
        open_geometry_rate_limiter, "retry_after", lambda *args, **kwargs: 5
    )
    first = client.post(url, headers=headers, json=turn())
    assert first.status_code == 429
    monkeypatch.setattr(
        open_geometry_rate_limiter, "retry_after", lambda *args, **kwargs: None
    )
    assert client.post(url, headers=headers, json=turn()).json() == first.json()
    assert not calls
