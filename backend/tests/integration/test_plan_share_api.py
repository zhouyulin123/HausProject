from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import shares
from app.db.database import Base, get_db
from app.db.models import DesignPlanVersion, DesignTask, PlanShare
from app.services import design_version_service, share_service
from app.services.anonymous_session_service import attach_task, create_anonymous_session


UNAVAILABLE_DETAIL = {
    "code": "share_unavailable",
    "message": "分享链接不存在或已失效",
}


def _context():
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
        task = DesignTask(status="completed", progress=100)
        db.add(task)
        db.flush()
        attach_task(db, owner.id, task.id)
        revision = design_version_service.persist_generation(
            db,
            task=task,
            plans=[
                {
                    "id": "plan-a",
                    "planVersionId": 987,
                    "task_id": 654,
                    "user": {"email": "private@example.com"},
                    "name": "服务端冻结方案",
                    "style": "原木风",
                    "description": "适合日常起居的克制方案，内部参考 D:\\private\\brief.txt",
                    "score": 91,
                    "budget": 128000,
                    "tags": ["收纳", "自然采光"],
                    "suitableFor": ["三口之家"],
                    "layoutSuggestions": ["保持主通道通畅"],
                    "aiTips": ["先确认现场尺寸"],
                    "furnitureSuggestions": [
                        {
                            "id": "private-product-id",
                            "sku": "SOFA-001",
                            "name": "三人沙发",
                            "category": "沙发",
                            "room": "客厅",
                            "style": "现代",
                            "material": "棉麻",
                            "priceRange": "¥5,000",
                            "sizeSuggestion": "2100×900×820mm",
                            "reason": "尺寸适配",
                            "quantity": 1,
                            "unitPrice": 5000,
                            "subtotal": 5000,
                            "imageUrl": "file:///D:/private/product.png",
                            "modelUrl": "D:/private/product.glb",
                            "sourceUrl": "https://internal.example/private",
                            "modelSpecJson": {"secret": "do-not-share"},
                        }
                    ],
                    "colorPalette": [
                        {"name": "米白", "hex": "#f3efe5", "usage": "墙面"}
                    ],
                    "materials": [
                        {"name": "白橡木", "description": "柜体饰面", "gradient": "private-css"}
                    ],
                    "lightingSuggestions": [
                        {"name": "无主灯", "purpose": "基础照明", "description": "均匀布光"}
                    ],
                    "budgetBreakdown": [
                        {"name": "家具", "percent": 50, "amount": 64000}
                    ],
                    "shopQuote": {
                        "furnitureTotal": 5000,
                        "customTotal": 0,
                        "total": 5000,
                        "lineItems": [
                            {
                                "sku": "SOFA-001",
                                "quantity": 1,
                                "unitPrice": 5000,
                                "subtotal": 5000,
                                "recordVersion": 9,
                            }
                        ],
                    },
                }
            ],
            generator="test",
        )
        db.commit()
        return (
            engine,
            factory,
            owner.id,
            stranger.id,
            task.id,
            revision.plans[0].id,
        )


def _client(factory):
    app = FastAPI()
    app.include_router(shares.owner_router, prefix="/api/design/shares")
    app.include_router(shares.public_router, prefix="/api/shares")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _create_share(client, owner_id, plan_version_id):
    return client.post(
        "/api/design/shares",
        headers={"X-Session-ID": owner_id},
        json={"plan_version_id": plan_version_id, "expires_in_hours": 24},
    )


def test_owner_creates_hashed_token_and_public_reads_only_whitelisted_snapshot():
    engine, factory, owner_id, _, _, plan_version_id = _context()
    try:
        with _client(factory) as client:
            created = _create_share(client, owner_id, plan_version_id)
            assert created.status_code == 201
            token = created.json()["token"]
            assert len(token) >= 32
            assert created.json()["share_url"] == f"/share/{token}"

            public = client.get(f"/api/shares/{token}")
            assert public.status_code == 200
            assert public.headers["cache-control"] == "no-store"
            assert public.headers["referrer-policy"] == "no-referrer"
            payload = public.json()

        with factory() as db:
            stored = db.query(PlanShare).one()
            assert stored.plan_version_id == plan_version_id
            assert stored.token_digest != token
            assert len(stored.token_digest) == 64
            assert "token" not in PlanShare.__table__.columns.keys()

        serialized = json.dumps(payload, ensure_ascii=False)
        assert payload["plan"]["name"] == "服务端冻结方案"
        assert payload["plan"]["furniture"][0]["sku"] == "SOFA-001"
        assert payload["plan"]["quote"]["total"] == 5000
        for forbidden in (
            "task_id",
            "plan_version_id",
            "user_id",
            "private@example.com",
            "file:///",
            "D:/private",
            "D:\\\\private",
            "modelSpecJson",
            "sourceUrl",
            "recordVersion",
            "private-product-id",
        ):
            assert forbidden not in serialized
    finally:
        engine.dispose()


def test_share_is_frozen_when_new_revision_and_original_rows_change():
    engine, factory, owner_id, _, task_id, plan_version_id = _context()
    try:
        with _client(factory) as client:
            created = _create_share(client, owner_id, plan_version_id)
            token = created.json()["token"]
            first = client.get(f"/api/shares/{token}").json()

            with factory() as db:
                task = db.get(DesignTask, task_id)
                design_version_service.persist_generation(
                    db,
                    task=task,
                    plans=[
                        {
                            "id": "plan-a",
                            "name": "后续方案",
                            "style": "轻奢",
                            "budget": 999999,
                            "shopQuote": {"total": 999999},
                        }
                    ],
                    generator="test",
                )
                original = db.get(DesignPlanVersion, plan_version_id)
                original.plan_json = {"name": "被错误改写的原始行"}
                original.quote_snapshot.grand_total = 1
                original.quote_snapshot.quote_json = {"total": 1}
                db.commit()

            second = client.get(f"/api/shares/{token}").json()

        assert second == first
        assert second["plan"]["name"] == "服务端冻结方案"
        assert second["plan"]["quote"]["total"] == 5000
    finally:
        engine.dispose()


def test_unknown_expired_revoked_and_foreign_revoke_are_indistinguishable():
    engine, factory, owner_id, stranger_id, _, plan_version_id = _context()
    try:
        with _client(factory) as client:
            foreign_create = _create_share(client, stranger_id, plan_version_id)
            assert foreign_create.status_code == 404

            first = _create_share(client, owner_id, plan_version_id).json()
            token = first["token"]
            unknown = client.get("/api/shares/not-a-real-share-token")
            foreign = client.post(
                f"/api/design/shares/{token}/revoke",
                headers={"X-Session-ID": stranger_id},
            )
            assert unknown.status_code == foreign.status_code == 404
            assert unknown.json()["detail"] == foreign.json()["detail"] == UNAVAILABLE_DETAIL

            revoked = client.post(
                f"/api/design/shares/{token}/revoke",
                headers={"X-Session-ID": owner_id},
            )
            after_revoke = client.get(f"/api/shares/{token}")
            assert revoked.status_code == 200
            assert after_revoke.status_code == 404
            assert after_revoke.json()["detail"] == UNAVAILABLE_DETAIL

            expired_created = _create_share(client, owner_id, plan_version_id).json()
            with factory() as db:
                expired = db.query(PlanShare).filter(
                    PlanShare.token_digest
                    == share_service.token_digest(expired_created["token"])
                ).one()
                expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
            expired_response = client.get(
                f"/api/shares/{expired_created['token']}"
            )
            assert expired_response.status_code == 404
            assert expired_response.json()["detail"] == UNAVAILABLE_DETAIL

            tampered_created = _create_share(client, owner_id, plan_version_id).json()
            with factory() as db:
                tampered = db.query(PlanShare).filter(
                    PlanShare.token_digest
                    == share_service.token_digest(tampered_created["token"])
                ).one()
                tampered.snapshot_json = {"name": "篡改内容"}
                db.commit()
            tampered_response = client.get(
                f"/api/shares/{tampered_created['token']}"
            )
            assert tampered_response.status_code == 404
            assert tampered_response.json()["detail"] == UNAVAILABLE_DETAIL
    finally:
        engine.dispose()
