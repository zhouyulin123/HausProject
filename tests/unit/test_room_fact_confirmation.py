from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask, RoomFactConfirmation, UploadedImage
from app.schemas.design_agent import AgentTurnRequest
from app.schemas.room_model import RoomModel
from app.services.design_agent_service import _facts_for_turn
from app.services.room_model_service import (
    apply_calibration,
    record_calibration_confirmations,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _model() -> RoomModel:
    return RoomModel.model_validate(
        {
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
                        {"x": 0, "z": 1},
                    ],
                    "widthM": 3.8,
                    "depthM": 4.6,
                    "confidence": 0.42,
                }
            ],
            "scale": {"source": "vl", "confidence": 0.42},
            "confidence": 0.42,
            "requiresConfirmation": ["roomDimensions", "spaceType"],
        }
    )


@pytest.mark.unit
def test_calibration_is_pure_and_records_append_only_fact_evidence(db):
    task = DesignTask(status="confirmed", confirmed_requirement_json={})
    db.add(task)
    db.commit()
    image = UploadedImage(
        task_id=task.id,
        file_url="/uploads/private-room.png",
        analysis_json={},
    )
    db.add(image)
    db.commit()
    original = _model()

    calibrated = apply_calibration(
        original,
        room_id="living",
        width_m=4.2,
        depth_m=5.1,
        ceiling_height=2.9,
    )
    first = record_calibration_confirmations(
        db,
        image=image,
        original=original,
        calibrated=calibrated,
        confirmed_by_session_id="session-001",
    )
    db.commit()

    assert original.rooms[0].width_m == 3.8
    assert calibrated.rooms[0].width_m == 4.2
    assert len(first) == 3
    width = next(item for item in first if item.fact_path.endswith(".width_m"))
    assert width.image_id == image.id
    assert width.task_id == task.id
    assert width.previous_value_json == 3.8
    assert width.confirmed_value_json == 4.2
    assert width.previous_confidence == 0.42
    assert width.confirmed_by_type == "anonymous_session"
    assert width.confirmed_by_id == "session-001"
    assert isinstance(width.confirmed_at, datetime)

    recalibrated = apply_calibration(
        calibrated,
        room_id="living",
        width_m=4.3,
        depth_m=5.1,
        ceiling_height=2.9,
    )
    record_calibration_confirmations(
        db,
        image=image,
        original=calibrated,
        calibrated=recalibrated,
        confirmed_by_session_id="session-001",
    )
    db.commit()

    history = db.scalars(
        select(RoomFactConfirmation)
        .where(RoomFactConfirmation.image_id == image.id)
        .order_by(RoomFactConfirmation.id)
    ).all()
    assert len(history) == 6
    assert [
        item.confirmed_value_json
        for item in history
        if item.fact_path.endswith(".width_m")
    ] == [4.2, 4.3]


@pytest.mark.unit
def test_calibration_rejects_unknown_room_instead_of_mutating_first_room():
    with pytest.raises(ValueError, match="房间不存在"):
        apply_calibration(
            _model(),
            room_id="unknown-room",
            width_m=4.2,
            depth_m=5.1,
        )


@pytest.mark.unit
def test_low_confidence_room_facts_wait_for_user_and_keep_evidence(db):
    task = DesignTask(status="confirmed", confirmed_requirement_json={})
    db.add(task)
    db.commit()
    model = _model()
    image = UploadedImage(
        task_id=task.id,
        file_url="/uploads/private-room.png",
        analysis_json={"room_model": model.model_dump(by_alias=True, mode="json")},
    )
    db.add(image)
    db.commit()
    payload = AgentTurnRequest(
        client_turn_id="turn-low-confidence-001",
        message="请设计这个空间",
        answers={
            "budget_max": 20000,
            "room_width_m": 4.2,
            "room_depth_m": 5.1,
            "delivery_region": "cn-sh",
        },
    )

    facts, evidence = _facts_for_turn(db, task, payload, turn_id=91)

    assert "space_type" not in facts
    assert evidence["space_type"] == {
        "source": "room_model",
        "confidence": 0.42,
        "image_id": image.id,
        "accepted": False,
        "confirmation_required": True,
    }
    assert evidence["room_width_m"]["source"] == "user_turn"
    assert evidence["room_width_m"]["turn_id"] == 91
    assert evidence["room_width_m"]["confidence"] == 1.0

    confirmed_payload = AgentTurnRequest(
        client_turn_id="turn-low-confidence-002",
        message="这是客厅",
        answers={"space_type": "客厅"},
    )
    confirmed_facts, confirmed_evidence = _facts_for_turn(
        db,
        task,
        confirmed_payload,
        turn_id=92,
    )

    assert confirmed_facts["space_type"] == "客厅"
    assert confirmed_evidence["space_type"] == {
        "source": "user_turn",
        "confidence": 1.0,
        "turn_id": 92,
        "accepted": True,
        "confirmation_required": False,
    }


@pytest.mark.unit
def test_legacy_calibration_without_confirmation_rows_is_not_trusted(db):
    task = DesignTask(status="confirmed", confirmed_requirement_json={})
    db.add(task)
    db.commit()
    original = _model()
    calibrated = apply_calibration(
        original,
        room_id="living",
        width_m=4.2,
        depth_m=5.1,
    )
    image = UploadedImage(
        task_id=task.id,
        file_url="/uploads/private-room.png",
        analysis_json={
            "room_model": calibrated.model_dump(by_alias=True, mode="json")
        },
    )
    db.add(image)
    db.commit()
    payload = AgentTurnRequest(
        client_turn_id="turn-legacy-calibration",
        message="继续设计",
        answers={"budget_max": 20000, "delivery_region": "CN-SH"},
    )

    facts, evidence = _facts_for_turn(db, task, payload, turn_id=93)

    assert "room_width_m" not in facts
    assert "room_depth_m" not in facts
    assert evidence["room_width_m"]["confirmation_required"] is True

    record_calibration_confirmations(
        db,
        image=image,
        original=original,
        calibrated=calibrated,
        confirmed_by_session_id="session-001",
    )
    db.commit()

    trusted_facts, trusted_evidence = _facts_for_turn(
        db,
        task,
        payload,
        turn_id=94,
    )
    assert trusted_facts["room_width_m"] == 4.2
    assert trusted_facts["room_depth_m"] == 5.1
    assert trusted_evidence["room_width_m"]["source"] == "user_confirmation"
    assert trusted_evidence["room_width_m"]["confirmation_id"] > 0
