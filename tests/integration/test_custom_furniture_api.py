import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import custom_furniture
from app.db.database import Base, get_db
from app.db.models import CustomQuoteRule, DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def custom_furniture_api_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(status="waiting_input", raw_user_input="定制一个衣柜")
        db.add(task)
        db.add(
            CustomQuoteRule(
                project_name="定制衣柜",
                category="柜类定制",
                pricing_unit="㎡",
                material_grade="E0 颗粒板",
                unit_price=680,
                is_active=True,
            )
        )
        db.commit()
        attach_task(db, owner.id, task.id)
        owner_id = owner.id
        stranger_id = stranger.id
        task_id = task.id

    app = FastAPI()
    app.include_router(custom_furniture.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, owner_id, stranger_id, task_id


def _request_body():
    return {
        "spec": {
            "family": "cabinet",
            "name": "主卧定制衣柜",
            "purpose": "wardrobe",
            "material": "E0 颗粒板",
            "dimensions": {
                "width_mm": 1200,
                "height_mm": 2400,
                "depth_mm": 600,
            },
            "structure": {
                "door_style": "hinged",
                "door_count": 3,
                "compartment_count": 3,
                "shelf_count": 4,
                "drawer_count": 2,
                "panel_thickness_mm": 18,
                "leg_height_mm": 80,
            },
        }
    }


@pytest.mark.integration
def test_owned_task_can_preview_custom_furniture(custom_furniture_api_context):
    client, owner_id, _, task_id = custom_furniture_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/custom-furniture-previews",
        headers={"X-Session-ID": owner_id},
        json=_request_body(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["status"] == "preview_ready"
    assert payload["quote_preview"]["estimated_amount"] == "1958.40"
    assert payload["model_spec"]["确定性建模规则"]["生成器"] == "cabinet_v2"


@pytest.mark.integration
def test_custom_furniture_preview_rejects_foreign_task(
    custom_furniture_api_context,
):
    client, _, stranger_id, task_id = custom_furniture_api_context

    response = client.post(
        f"/api/design/tasks/{task_id}/custom-furniture-previews",
        headers={"X-Session-ID": stranger_id},
        json=_request_body(),
    )

    assert response.status_code == 404


@pytest.mark.integration
def test_custom_furniture_preview_rejects_missing_dimensions(
    custom_furniture_api_context,
):
    client, owner_id, _, task_id = custom_furniture_api_context
    body = _request_body()
    del body["spec"]["dimensions"]

    response = client.post(
        f"/api/design/tasks/{task_id}/custom-furniture-previews",
        headers={"X-Session-ID": owner_id},
        json=body,
    )

    assert response.status_code == 422
    assert "dimensions" in response.text
