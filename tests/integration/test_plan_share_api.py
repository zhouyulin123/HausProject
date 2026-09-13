from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from threading import Event

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from app.api.routes import shares
from app.db.database import Base, get_db
from app.db.models import DesignPlanVersion, DesignTask, PlanShare
from app.services import (
    aggregate_lock_service,
    design_version_service,
    plan_delivery_service,
    share_service,
)
from app.services.anonymous_session_service import attach_task, create_anonymous_session
from tests.real_world_fixtures import frozen_catalog_quote_line, frozen_catalog_suggestion


UNAVAILABLE_DETAIL = {
    "code": "share_unavailable",
    "message": "分享链接不存在或已失效",
}


def _context(engine=None):
    engine = engine or create_engine(
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
        suggestion = frozen_catalog_suggestion(sku="SOFA-001", unit_price=5000)
        eligibility = suggestion["catalogEligibility"]
        suggestion.update(
            {
                "name": "三人沙发",
                "category": "沙发",
                "room": "客厅",
                "style": "现代",
                "material": "棉麻",
                "priceRange": "¥5,000",
                "sizeSuggestion": "2100×900×820mm",
                "reason": "尺寸适配",
                "subtotal": 5000,
                "imageUrl": "file:///D:/private/product.png",
                "modelUrl": "D:/private/product.glb",
                "sourceUrl": eligibility["facts"]["sourceUrl"],
                "modelSpecJson": {"secret": "do-not-share"},
                "dataStatus": "verified",
                "sourceName": eligibility["facts"]["sourceName"],
                "verifiedAt": eligibility["facts"]["verifiedAt"],
            }
        )
        quote_line = frozen_catalog_quote_line(suggestion)
        quote_line["subtotal"] = 5000
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
                    "furnitureSuggestions": [suggestion],
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
                        "catalogVersion": "catalog-v1",
                        "priceVersion": "prices-v1",
                        "ruleVersion": "rules-v1",
                        "pricedAt": "2026-09-01T00:00:00+00:00",
                        "lineItems": [quote_line],
                        "customLineItems": [],
                    },
                }
            ],
            generator="llm",
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
        assert "score" not in payload["plan"]
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


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("legacy_quote", "catalog_version_missing"),
        ("quote_inconsistent", "quote_snapshot_inconsistent"),
        ("product_source_missing", "product_source_missing"),
        ("eligibility_missing", "product_eligibility_missing"),
        ("eligibility_tampered", "out_of_stock"),
        ("source_reference_missing", "source_reference_missing"),
        ("product_fact_mismatch", "product_eligibility_facts_mismatch"),
        ("draft_policy", "product_eligibility_policy_mismatch"),
        ("generation_source_missing", "generation_source_untrusted"),
    ],
)
def test_share_creation_rejects_untrusted_delivery_snapshot(mutation, reason_code):
    engine, factory, owner_id, _, _, plan_version_id = _context()
    try:
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            if mutation == "legacy_quote":
                plan.quote_snapshot.catalog_version = "legacy"
            elif mutation == "quote_inconsistent":
                plan.quote_snapshot.grand_total += 1
            elif mutation == "product_source_missing":
                payload = deepcopy(plan.plan_json)
                payload["furnitureSuggestions"][0]["sourceName"] = ""
                plan.plan_json = payload
            elif mutation == "eligibility_missing":
                payload = deepcopy(plan.plan_json)
                payload["furnitureSuggestions"][0].pop("catalogEligibility")
                plan.plan_json = payload
            elif mutation == "eligibility_tampered":
                payload = deepcopy(plan.plan_json)
                payload["furnitureSuggestions"][0]["catalogEligibility"]["facts"][
                    "availabilityStatus"
                ] = "out_of_stock"
                plan.plan_json = payload
            elif mutation == "source_reference_missing":
                payload = deepcopy(plan.plan_json)
                facts = payload["furnitureSuggestions"][0]["catalogEligibility"][
                    "facts"
                ]
                facts["sourceUrl"] = None
                facts["sourceProductId"] = ""
                plan.plan_json = payload
            elif mutation == "product_fact_mismatch":
                payload = deepcopy(plan.plan_json)
                payload["furnitureSuggestions"][0]["sourceName"] = "伪造来源"
                plan.plan_json = payload
            elif mutation == "draft_policy":
                payload = deepcopy(plan.plan_json)
                payload["furnitureSuggestions"][0]["catalogEligibility"][
                    "policy"
                ]["allowDraft"] = True
                plan.plan_json = payload
            else:
                plan.revision.generator = "legacy"
            db.commit()

        with _client(factory) as client:
            response = _create_share(client, owner_id, plan_version_id)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plan_delivery_blocked"
        assert reason_code in response.json()["detail"]["reason_codes"]
        with factory() as db:
            assert db.query(PlanShare).count() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("generator", ["template", "demo", "test", "unknown", "deepseek"])
def test_share_creation_rejects_generators_outside_formal_allowlist(generator):
    engine, factory, owner_id, _, _, plan_version_id = _context()
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        plan.revision.generator = generator
        db.commit()

    with _client(factory) as client:
        response = _create_share(client, owner_id, plan_version_id)

    assert response.status_code == 409
    assert response.json()["detail"]["reason_codes"] == [
        "generation_source_untrusted"
    ]
    with factory() as db:
        assert db.query(PlanShare).count() == 0
    engine.dispose()


def test_share_creation_rejects_derived_revision_without_verified_source_chain():
    engine, factory, owner_id, _, _, plan_version_id = _context()
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        plan.revision.generator = "refine"
        plan.revision.workflow_trace_snapshot = [
            {"node": "plan_refine", "status": "completed"}
        ]
        db.commit()

    with _client(factory) as client:
        response = _create_share(client, owner_id, plan_version_id)

    assert response.status_code == 409
    assert response.json()["detail"]["reason_codes"] == [
        "generation_source_chain_invalid"
    ]
    engine.dispose()


def test_share_expiry_is_capped_by_frozen_quote_validity():
    engine, factory, owner_id, _, _, plan_version_id = _context()
    price_valid_to = datetime.now(timezone.utc) + timedelta(hours=2)
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        eligibility = plan.plan_json["furnitureSuggestions"][0][
            "catalogEligibility"
        ]
        eligibility["facts"]["priceValidTo"] = price_valid_to.isoformat()
        flag_modified(plan, "plan_json")
        db.commit()

    with _client(factory) as client:
        response = client.post(
            "/api/design/shares",
            headers={"X-Session-ID": owner_id},
            json={"plan_version_id": plan_version_id, "expires_in_hours": 720},
        )

    assert response.status_code == 201
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at <= price_valid_to
    assert expires_at > datetime.now(timezone.utc)
    engine.dispose()


def test_share_rejects_frozen_policy_not_bound_to_revision_constraints():
    engine, factory, owner_id, _, _, plan_version_id = _context()
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        plan.revision.requirement_snapshot = {"delivery_region": "CN-SH"}
        db.commit()

    with _client(factory) as client:
        response = _create_share(client, owner_id, plan_version_id)

    assert response.status_code == 409
    assert "product_eligibility_policy_mismatch" in response.json()["detail"][
        "reason_codes"
    ]
    engine.dispose()


def test_share_fails_closed_if_snapshot_changes_after_delivery_audit(monkeypatch):
    engine, factory, owner_id, _, _, plan_version_id = _context()
    original_gate = plan_delivery_service.require_deliverable

    def mutate_after_audit(plan_version, **kwargs):
        facts = original_gate(plan_version, **kwargs)
        changed = deepcopy(plan_version.plan_json)
        changed["name"] = "校验后被替换的方案"
        plan_version.plan_json = changed
        return facts

    monkeypatch.setattr(
        plan_delivery_service,
        "require_deliverable",
        mutate_after_audit,
    )
    with _client(factory) as client:
        response = _create_share(client, owner_id, plan_version_id)

    assert response.status_code == 409
    assert response.json()["detail"]["reason_codes"] == [
        "delivery_snapshot_changed"
    ]
    with factory() as db:
        assert db.query(PlanShare).count() == 0
    engine.dispose()


def test_share_holds_delivery_aggregate_lock_until_snapshot_commit(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "plan-share-lock.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0},
    )
    _, factory, _, _, _, plan_version_id = _context(engine)
    share_reached_commit = Event()
    mutation_finished = Event()
    original_token = share_service.secrets.token_urlsafe

    def coordinated_token(length):
        share_reached_commit.set()
        assert mutation_finished.wait(timeout=5)
        return original_token(length)

    monkeypatch.setattr(share_service.secrets, "token_urlsafe", coordinated_token)

    def create_share():
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            return share_service.create_share(
                db,
                plan_version=plan,
                expires_in_hours=24,
            )

    def mutate_plan():
        assert share_reached_commit.wait(timeout=5)
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            changed = deepcopy(plan.plan_json)
            changed["name"] = "审计后并发改写"
            plan.plan_json = changed
            try:
                db.commit()
            except OperationalError as exc:
                db.rollback()
                assert "locked" in str(exc).lower() or "busy" in str(exc).lower()
                outcome = "locked"
            else:
                outcome = "committed"
        mutation_finished.set()
        return outcome

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            share_future = executor.submit(create_share)
            mutation_future = executor.submit(mutate_plan)
            mutation_outcome = mutation_future.result(timeout=5)
            share, _ = share_future.result(timeout=5)

        assert mutation_outcome == "locked"
        assert share.snapshot_json["name"] == "服务端冻结方案"
        with factory() as db:
            assert db.get(DesignPlanVersion, plan_version_id).plan_json["name"] == (
                "服务端冻结方案"
            )
            assert db.query(PlanShare).count() == 1
    finally:
        engine.dispose()


def test_share_token_collision_does_not_release_delivery_lock(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "plan-share-token-collision.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 0},
    )
    _, factory, _, _, _, plan_version_id = _context(engine)
    duplicate_token = "duplicate-share-token"
    unique_token = "unique-share-token"
    with factory() as db:
        db.add(
            PlanShare(
                plan_version_id=plan_version_id,
                token_digest=share_service.token_digest(duplicate_token),
                snapshot_json={},
                snapshot_digest="sha256:" + "0" * 64,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.commit()

    retry_reached = Event()
    mutation_finished = Event()
    tokens = iter((duplicate_token, unique_token))

    def coordinated_token(_length):
        token = next(tokens)
        if token == unique_token:
            retry_reached.set()
            assert mutation_finished.wait(timeout=5)
        return token

    monkeypatch.setattr(share_service.secrets, "token_urlsafe", coordinated_token)

    def create_share():
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            return share_service.create_share(
                db,
                plan_version=plan,
                expires_in_hours=24,
            )

    def mutate_quote():
        assert retry_reached.wait(timeout=5)
        with factory() as db:
            plan = db.get(DesignPlanVersion, plan_version_id)
            plan.quote_snapshot.grand_total = 1
            try:
                db.commit()
            except OperationalError as exc:
                db.rollback()
                assert "locked" in str(exc).lower() or "busy" in str(exc).lower()
                outcome = "locked"
            else:
                outcome = "committed"
        mutation_finished.set()
        return outcome

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            share_future = executor.submit(create_share)
            mutation_future = executor.submit(mutate_quote)
            mutation_outcome = mutation_future.result(timeout=5)
            share, token = share_future.result(timeout=5)

        assert mutation_outcome == "locked"
        assert token == unique_token
        assert share.snapshot_json["quote"]["total"] == 5000
        with factory() as db:
            assert db.get(DesignPlanVersion, plan_version_id).quote_snapshot.grand_total == 5000
            assert db.query(PlanShare).count() == 2
    finally:
        engine.dispose()


def test_share_reports_busy_delivery_aggregate_as_conflict(monkeypatch):
    engine, factory, owner_id, _, _, plan_version_id = _context()

    def raise_busy(*_args, **_kwargs):
        raise aggregate_lock_service.AggregateLockBusy("busy")

    monkeypatch.setattr(
        plan_delivery_service,
        "lock_delivery_aggregate",
        raise_busy,
    )
    try:
        with _client(factory) as client:
            response = _create_share(client, owner_id, plan_version_id)

        assert response.status_code == 409
        assert response.json()["detail"]["reason_codes"] == [
            "delivery_snapshot_busy"
        ]
        with factory() as db:
            assert db.query(PlanShare).count() == 0
    finally:
        engine.dispose()


def test_share_binds_quote_total_to_revision_budget_constraint():
    engine, factory, owner_id, _, _, plan_version_id = _context()
    with factory() as db:
        plan = db.get(DesignPlanVersion, plan_version_id)
        plan.revision.requirement_snapshot = {"budget_max": 4_000}
        db.commit()

    with _client(factory) as client:
        response = _create_share(client, owner_id, plan_version_id)

    assert response.status_code == 409
    assert "quote_budget_exceeded" in response.json()["detail"]["reason_codes"]
    engine.dispose()


def test_share_accepts_derived_revision_with_verified_source_chain():
    engine, factory, owner_id, _, task_id, plan_version_id = _context()
    with factory() as db:
        source_plan = db.get(DesignPlanVersion, plan_version_id)
        source_revision = source_plan.revision
        task = db.get(DesignTask, task_id)
        derived = design_version_service.persist_generation(
            db,
            task=task,
            plans=[deepcopy(source_plan.plan_json)],
            generator="refine",
            workflow_trace=[
                {
                    "node": "plan_refine",
                    "status": "completed",
                    "source_revision_id": source_revision.id,
                    "source_revision_version": source_revision.version,
                }
            ],
        )
        db.commit()
        derived_plan_version_id = derived.plans[0].id

    with _client(factory) as client:
        response = _create_share(client, owner_id, derived_plan_version_id)

    assert response.status_code == 201
    engine.dispose()
