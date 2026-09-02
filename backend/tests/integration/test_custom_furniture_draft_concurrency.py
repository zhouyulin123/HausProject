from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import design_agent
from app.db.database import Base, get_db
from app.db.models import (
    CustomFurnitureDraftMutation,
    DesignAgentTurn,
    DesignTask,
)
from app.services import design_agent_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


def _draft_payload(index: int) -> dict:
    return {
        "client_mutation_id": f"draft-concurrency-{index}",
        "base_state_version": 0,
        "custom_furniture_spec": {
            "family": "table",
            "name": f"并发餐桌 {index}",
            "purpose": "dining_table",
            "material": "实木（橡木）",
            "dimensions": {
                "width_mm": 1600,
                "height_mm": 760,
                "depth_mm": 800,
            },
            "structure": {
                "top_shape": "rectangle",
                "base_style": "four_leg",
                "support_count": 4,
                "seat_count": 6,
                "top_thickness_mm": 30,
                "edge_radius_mm": 8,
            },
        },
    }


@pytest.fixture
def custom_draft_file_context(tmp_path):
    database_path = tmp_path / "custom-furniture-draft-concurrency.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        task = DesignTask(
            status="completed",
            progress=100,
            active_mode="custom_furniture",
        )
        db.add(task)
        db.commit()
        attach_task(db, owner.id, task.id)
        values = {"owner": owner.id, "task_id": task.id}

    app = FastAPI()
    app.include_router(design_agent.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield {"app": app, "factory": factory, **values}
    finally:
        engine.dispose()


@pytest.mark.integration
def test_different_drafts_are_serialized_without_lost_update(
    custom_draft_file_context,
    monkeypatch,
):
    context = custom_draft_file_context
    first_in_lock = Event()
    release_first = Event()
    original_save = design_agent_service.save_custom_furniture_draft

    def delayed_save(db, *, task, payload):
        if payload.client_mutation_id == "draft-concurrency-1":
            first_in_lock.set()
            assert release_first.wait(timeout=5)
        return original_save(db, task=task, payload=payload)

    monkeypatch.setattr(
        design_agent_service,
        "save_custom_furniture_draft",
        delayed_save,
    )
    url = f"/api/design/tasks/{context['task_id']}/custom-furniture-draft"
    headers = {"X-Session-ID": context["owner"]}

    def submit(payload: dict):
        with TestClient(context["app"], raise_server_exceptions=False) as client:
            return client.put(url, headers=headers, json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(submit, _draft_payload(1))
        assert first_in_lock.wait(timeout=5)
        second = executor.submit(submit, _draft_payload(2))
        release_first.set()
        responses = [first.result(timeout=5), second.result(timeout=5)]

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert all(response.status_code != 500 for response in responses)
    conflict = next(response for response in responses if response.status_code == 409)
    detail = conflict.json()["detail"]
    assert detail["code"] == "agent_state_conflict"
    assert detail["state_version"] == 1
    assert detail["custom_furniture_draft"] == _draft_payload(1)[
        "custom_furniture_spec"
    ]

    with context["factory"]() as db:
        assert db.get(DesignTask, context["task_id"]).agent_state_version == 1
        assert db.scalar(select(func.count(CustomFurnitureDraftMutation.id))) == 1
        assert db.scalar(select(func.count(DesignAgentTurn.id))) == 0
