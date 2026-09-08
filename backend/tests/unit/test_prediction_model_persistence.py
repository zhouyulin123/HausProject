from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.api.routes import tasks, upload
from app.db.database import Base
from app.db.models import (
    DesignTask,
    RequirementParseResult,
    TaskExecutionEvent,
    UploadedImage,
)
from app.services.llm_service import LLMUnavailable


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _room_model():
    return {
        "schemaVersion": "1.0",
        "imageKind": "floor_plan",
        "spaceType": "客厅",
        "rooms": [
            {
                "id": "living",
                "name": "客厅",
                "floorPolygon": [
                    {"x": 0, "z": 0},
                    {"x": 1, "z": 0},
                    {"x": 1, "z": 1},
                ],
            }
        ],
    }


def test_requirement_route_persists_actual_llm_model(db, monkeypatch):
    task = DesignTask(status="analyzing", raw_user_input="需要现代客厅")
    db.add(task)
    db.commit()
    monkeypatch.setattr(tasks, "require_owned_design_task", lambda *_args, **_kwargs: task)
    monkeypatch.setattr(
        tasks.llm_service,
        "parse_requirement",
        lambda _raw: {"space_type": "客厅"},
    )
    monkeypatch.setattr(tasks.settings, "llm_model", "actual-llm-v7")

    response = tasks.get_requirement(task.id, "session-001", db)

    saved = db.query(RequirementParseResult).filter_by(task_id=task.id).one()
    assert response.parser == "llm"
    assert saved.parser_model == "actual-llm-v7"


def test_requirement_route_records_metered_model_call_in_task_timeline(
    db, monkeypatch
):
    task = DesignTask(status="analyzing", raw_user_input="需要现代客厅")
    db.add(task)
    db.commit()
    monkeypatch.setattr(tasks, "require_owned_design_task", lambda *_args, **_kwargs: task)
    monkeypatch.setattr(
        tasks.llm_service,
        "parse_requirement",
        lambda _raw: {"space_type": "客厅"},
    )

    @contextmanager
    def captured_call():
        yield SimpleNamespace(
            attempted=True,
            usage={"prompt_tokens": 100, "completion_tokens": 50},
        )

    monkeypatch.setattr(tasks.llm_service, "capture_model_call", captured_call)
    monkeypatch.setattr(tasks.settings, "llm_input_price_per_mtok", 2.0)
    monkeypatch.setattr(tasks.settings, "llm_output_price_per_mtok", 8.0)

    tasks.get_requirement(task.id, "session-001", db)

    saved = db.query(RequirementParseResult).filter_by(task_id=task.id).one()
    event = db.query(TaskExecutionEvent).filter_by(task_id=task.id).one()
    assert saved.model_call_attempted is True
    assert saved.billing_status == "metered"
    assert saved.cost_cny == pytest.approx(0.0006)
    assert event.source_type == "requirement"
    assert event.source_id == saved.id
    assert event.event_code == "requirement.completed"
    assert event.billing_status == "metered"
    assert event.cost_cny == pytest.approx(0.0006)


def test_requirement_rule_fallback_keeps_model_null(db, monkeypatch):
    task = DesignTask(status="analyzing", raw_user_input="需要现代客厅")
    db.add(task)
    db.commit()
    monkeypatch.setattr(tasks, "require_owned_design_task", lambda *_args, **_kwargs: task)
    monkeypatch.setattr(
        tasks.llm_service,
        "parse_requirement",
        lambda _raw: (_ for _ in ()).throw(LLMUnavailable("offline")),
    )

    response = tasks.get_requirement(task.id, "session-001", db)

    saved = db.query(RequirementParseResult).filter_by(task_id=task.id).one()
    assert response.parser == "rule"
    assert saved.parser_model is None


def test_requirement_route_reuses_same_input_without_duplicate_model_call(
    db, monkeypatch
):
    task = DesignTask(status="analyzing", raw_user_input="需要现代客厅")
    db.add(task)
    db.commit()
    monkeypatch.setattr(tasks, "require_owned_design_task", lambda *_args, **_kwargs: task)
    calls = 0

    def parse_once(_raw):
        nonlocal calls
        calls += 1
        return {
            "space_type": "客厅",
            "missing_fields": ["budget"],
            "follow_up_questions": ["预算范围大概是多少？"],
        }

    monkeypatch.setattr(tasks.llm_service, "parse_requirement", parse_once)

    first = tasks.get_requirement(task.id, "session-001", db)
    second = tasks.get_requirement(task.id, "session-001", db)

    assert calls == 1
    assert second == first
    assert db.query(RequirementParseResult).filter_by(task_id=task.id).count() == 1
    assert db.query(TaskExecutionEvent).filter_by(task_id=task.id).count() == 1


@pytest.mark.asyncio
async def test_upload_route_persists_actual_vl_model(db, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(upload, "require_active_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        upload,
        "validate_image_upload",
        lambda **_kwargs: SimpleNamespace(extension="png"),
    )
    monkeypatch.setattr(upload.llm_service, "analyze_room_model", lambda *_args: _room_model())
    monkeypatch.setattr(
        upload.anonymous_session_service,
        "attach_image",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(upload.settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(upload.settings, "vl_model", "actual-vl-v9")
    image_file = UploadFile(
        BytesIO(b"validated-image"),
        filename="floor-plan.png",
        headers=Headers({"content-type": "image/png"}),
    )

    await upload.upload_image("session-001", image_file, None, db)

    saved = db.query(UploadedImage).one()
    assert saved.original_prediction_source == "vl"
    assert saved.original_prediction_model == "actual-vl-v9"


@pytest.mark.asyncio
async def test_upload_route_records_visual_model_cost_for_bound_task(
    db, monkeypatch, tmp_path: Path
):
    task = DesignTask(status="analyzing", raw_user_input="分析户型")
    db.add(task)
    db.commit()
    monkeypatch.setattr(upload, "require_active_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        upload,
        "require_owned_design_task",
        lambda *_args, **_kwargs: task,
    )
    monkeypatch.setattr(
        upload,
        "validate_image_upload",
        lambda **_kwargs: SimpleNamespace(extension="png"),
    )
    monkeypatch.setattr(upload.llm_service, "analyze_room_model", lambda *_args: _room_model())

    @contextmanager
    def captured_call():
        yield SimpleNamespace(
            attempted=True,
            usage={"prompt_tokens": 250, "completion_tokens": 100},
        )

    monkeypatch.setattr(upload.llm_service, "capture_model_call", captured_call)
    monkeypatch.setattr(
        upload.anonymous_session_service,
        "attach_image",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(upload.settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(upload.settings, "vl_input_price_per_mtok", 1.0)
    monkeypatch.setattr(upload.settings, "vl_output_price_per_mtok", 5.0)
    image_file = UploadFile(
        BytesIO(b"validated-image"),
        filename="floor-plan.png",
        headers=Headers({"content-type": "image/png"}),
    )

    await upload.upload_image("session-001", image_file, task.id, db)

    saved = db.query(UploadedImage).one()
    event = db.query(TaskExecutionEvent).filter_by(task_id=task.id).one()
    assert saved.analysis_model_call_attempted is True
    assert saved.analysis_billing_status == "metered"
    assert saved.analysis_cost_cny == pytest.approx(0.00075)
    assert event.source_type == "vision"
    assert event.source_id == saved.id
    assert event.event_code == "vision.completed"
    assert event.billing_status == "metered"
    assert event.cost_cny == pytest.approx(0.00075)


@pytest.mark.asyncio
async def test_upload_placeholder_keeps_model_null(db, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(upload, "require_active_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        upload,
        "validate_image_upload",
        lambda **_kwargs: SimpleNamespace(extension="png"),
    )
    monkeypatch.setattr(upload.llm_service, "analyze_room_model", lambda *_args: None)
    monkeypatch.setattr(
        upload.anonymous_session_service,
        "attach_image",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(upload.settings, "upload_dir", str(tmp_path / "uploads"))
    image_file = UploadFile(
        BytesIO(b"validated-image"),
        filename="floor-plan.png",
        headers=Headers({"content-type": "image/png"}),
    )

    await upload.upload_image("session-001", image_file, None, db)

    saved = db.query(UploadedImage).one()
    assert saved.original_prediction_source == "placeholder"
    assert saved.original_prediction_model is None
