from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.api.routes import tasks, upload
from app.db.database import Base
from app.db.models import DesignTask, RequirementParseResult, UploadedImage
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
