"""整屋估价必须绑定版本，缺失商业证据不能计成零元。"""
# ruff: noqa: F811

from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest

from app.db.models import CustomQuoteRule, DesignSpaceVersion, Product, HomeDesignQuote
from tests.integration.test_home_assets_independent import (  # noqa: F401
    assets_context,
    spatial_context,
    freeze,
    bound_document,
)


def prepare(context, commercial=True):
    client, factory, url, headers, _, product_id, _ = context
    if commercial:
        now = datetime.now(timezone.utc)
        with factory() as db:
            p = db.get(Product, product_id)
            for key, value in dict(
                data_origin="merchant",
                source_name="测试授权目录",
                source_product_id="fixture",
                source_retrieved_at=now - timedelta(days=1),
                price_observed_at=now - timedelta(days=1),
                verification_status="verified",
                verified_at=now - timedelta(hours=1),
                verified_by="test-reviewer",
                data_version="quote-fixture-v1",
                availability_status="in_stock",
                stock_quantity=5,
                region_codes=["CN-SH"],
                price_valid_from=now - timedelta(days=1),
                price_valid_to=now + timedelta(days=1),
                model_width_mm=720,
                model_height_mm=790,
                model_depth_mm=780,
            ).items():
                setattr(p, key, value)
            db.commit()
    asset = freeze(client, url, headers, product_id).json()
    response = client.put(
        url,
        headers=headers,
        json={
            "base_version": 0,
            "client_mutation_id": "home",
            "document": bound_document(asset),
        },
    )
    assert response.status_code == 200, response.text
    return client, factory, url, headers, product_id


def test_quote_is_immutable_and_replay_keeps_price(assets_context):
    client, factory, url, headers, product_id = prepare(assets_context)
    payload = dict(home_version=1, region="CN-SH", client_mutation_id="quote")
    response = client.post(url + "/quotes", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"].lower() == "x-session-id"
    quote = response.json()
    assert quote["snapshot"]["known_subtotal"] == 100
    assert quote["snapshot"]["pending_count"] == 0
    assert quote["snapshot"]["lines"][0]["unit_price"] == 100
    with factory() as db:
        p = db.get(Product, product_id)
        p.price = 999
        p.record_version = 2
        db.commit()
    assert client.post(url + "/quotes", headers=headers, json=payload).json() == quote
    assert client.get(url + f"/quotes/{quote['id']}", headers=headers).json() == quote
    pending = client.post(
        url + "/quotes",
        headers=headers,
        json={**payload, "client_mutation_id": "updated"},
    ).json()["snapshot"]
    assert pending["pending_count"] == 1
    assert pending["total_price"] is None
    assert pending["lines"][0]["unit_price"] is None
    conflict = client.post(
        url + "/quotes", headers=headers, json={**payload, "region": "CN-BJ"}
    )
    assert conflict.status_code == 409
    assert conflict.headers["cache-control"] == "no-store"
    assert conflict.headers["vary"].lower() == "x-session-id"


def test_quote_unknown_prices_and_permissions(assets_context):
    client, _, url, headers, _ = prepare(assets_context, False)
    payload = dict(home_version=1, region="CN-SH", client_mutation_id="quote")
    result = client.post(url + "/quotes", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    quote = result.json()
    assert quote["snapshot"]["known_subtotal"] == 0
    assert quote["snapshot"]["total_price"] is None
    assert quote["snapshot"]["pending_count"] == 1
    assert (
        client.get(
            url + f"/quotes/{quote['id']}", headers={"X-Session-ID": assets_context[4]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            url + "/quotes",
            headers=headers,
            json={**payload, "home_version": 99, "client_mutation_id": "missing"},
        ).status_code
        == 404
    )


def test_corrupt_snapshot_fails_closed_on_read_list_and_replay(assets_context):
    client, factory, url, headers, _ = prepare(assets_context)
    payload = dict(home_version=1, region="CN-SH", client_mutation_id="corrupt")
    quote = client.post(url + "/quotes", headers=headers, json=payload).json()
    with factory() as db:
        row = db.get(HomeDesignQuote, quote["id"])
        snapshot = deepcopy(row.snapshot_json)
        snapshot["known_subtotal"] = 1
        row.snapshot_json = snapshot
        db.commit()
    assert (
        client.get(url + f"/quotes/{quote['id']}", headers=headers).status_code == 409
    )
    assert (
        client.get(url + "/quotes?home_version=1", headers=headers).status_code == 409
    )
    assert (
        client.post(url + "/quotes", headers=headers, json=payload).status_code == 409
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("stock_quantity", 1),
        ("region_codes", ["CN-BJ"]),
        ("verification_status", "draft"),
        ("price_max", 120),
        ("data_origin", "public_reference"),
        ("is_active", False),
    ],
)
def test_commercial_failures_preserve_pending(assets_context, field, value):
    client, factory, url, headers, product_id = prepare(assets_context)
    current = client.get(url, headers=headers).json()["document"]
    extra = deepcopy(current["objects"][0])
    extra["id"] = "second-chair"
    current["objects"].append(extra)
    assert (
        client.put(
            url,
            headers=headers,
            json={
                "base_version": 1,
                "client_mutation_id": "two-chairs",
                "document": current,
            },
        ).status_code
        == 200
    )
    with factory() as db:
        setattr(db.get(Product, product_id), field, value)
        db.commit()
    result = client.post(
        url + "/quotes",
        headers=headers,
        json={"home_version": 2, "region": "CN-SH", "client_mutation_id": "pending"},
    )
    assert result.status_code == 200, result.text
    snapshot = result.json()["snapshot"]
    assert snapshot["pending_count"] == 2
    assert snapshot["total_price"] is None
    assert all(
        line["reasons"] and line["unit_price"] is None for line in snapshot["lines"]
    )
    assert snapshot["validation"]["valid"] is False
    assert snapshot["scale_status"] == "unconfirmed"


def test_mixed_empty_pagination_and_same_owner_other_task(assets_context):
    client, _, url, headers, _ = prepare(assets_context)
    current = client.get(url, headers=headers).json()["document"]
    current["surfaces"] = [
        {
            "id": "floor",
            "room_id": current["objects"][0]["room_id"],
            "kind": "floor",
            "material": {"name": "待选地板", "color": "#ffffff"},
        }
    ]
    assert (
        client.put(
            url,
            headers=headers,
            json={
                "base_version": 1,
                "client_mutation_id": "mixed",
                "document": current,
            },
        ).status_code
        == 200
    )
    payload = {"home_version": 2, "region": "CN-SH", "client_mutation_id": "mixed"}
    quote = client.post(url + "/quotes", headers=headers, json=payload).json()
    snapshot = quote["snapshot"]
    assert snapshot["known_subtotal"] == 100
    assert snapshot["pending_count"] == 1 and snapshot["total_price"] is None
    other_url = url.rsplit("/", 2)[0] + f"/{assets_context[6]}/home-design"
    assert (
        client.get(other_url + f"/quotes/{quote['id']}", headers=headers).status_code
        == 404
    )
    for index in range(2):
        assert (
            client.post(
                url + "/quotes",
                headers=headers,
                json={**payload, "client_mutation_id": f"p{index}"},
            ).status_code
            == 200
        )
    page = client.get(url + "/quotes?home_version=2&limit=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["next_before_id"]
    next_page = client.get(
        url + f"/quotes?home_version=2&limit=2&before_id={page['next_before_id']}",
        headers=headers,
    ).json()
    assert [x["id"] for x in next_page["items"]] == [quote["id"]]
    current["surfaces"], current["objects"] = [], []
    assert (
        client.put(
            url,
            headers=headers,
            json={
                "base_version": 2,
                "client_mutation_id": "empty",
                "document": current,
            },
        ).status_code
        == 200
    )
    empty = client.post(
        url + "/quotes",
        headers=headers,
        json={**payload, "home_version": 3, "client_mutation_id": "empty"},
    ).json()["snapshot"]
    assert empty["lines"] == [] and empty["total_price"] is None


def test_surface_rule_quote_freezes_full_deterministic_evidence(assets_context):
    client, factory, url, headers, _ = prepare(assets_context)
    with factory() as db:
        space = db.query(DesignSpaceVersion).filter_by(task_id=int(url.split("/")[-2]), version=1).one()
        document_json = deepcopy(space.document_json)
        document_json["scale_status"] = "confirmed"
        space.document_json = document_json
        rule = CustomQuoteRule(
            project_name="客厅地砖",
            category="地面材料",
            pricing_unit="㎡",
            material_grade="标准",
            unit_price=100,
            region_codes=["CN-SH"],
            waste_rate_bps=1000,
            minimum_quantity=15,
            installation_fee=200,
            shipping_fee=100,
            tax_rate_bps=600,
            data_version="surface-price-v3",
            record_version=3,
            is_active=True,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id
    current = client.get(url, headers=headers).json()["document"]
    current["objects"] = []
    current["surfaces"] = [{
        "id": "floor",
        "room_id": "r1",
        "kind": "floor",
        "material": {"name": "任意展示名，不用于匹配", "color": "#eeeeee"},
        "quote_rule_id": rule_id,
    }]
    saved = client.put(url, headers=headers, json={
        "base_version": 1,
        "client_mutation_id": "surface-rule",
        "document": current,
    })
    assert saved.status_code == 200, saved.text

    payload = {"home_version": 2, "region": "CN-SH", "client_mutation_id": "material"}
    response = client.post(url + "/quotes", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    snapshot = response.json()["snapshot"]
    line = snapshot["lines"][0]
    assert snapshot["known_subtotal"] == 1908
    assert snapshot["pending_count"] == 0
    assert snapshot["total_price"] == 1908
    assert line["quantity"] == 12
    assert line["unit_price"] == 100
    assert line["total_price"] == 1908
    assert line["source_id"] == rule_id
    assert line["source_version"] == 3
    assert line["source_data_version"] == "surface-price-v3"
    assert line["rule_evidence"]["requestedQuantity"] == 12
    assert line["rule_evidence"]["billableQuantity"] == 15
    assert line["rule_evidence"]["subtotal"] == 1908
    assert len(line["rule_evidence_digest"]) == 64

    with factory() as db:
        rule = db.get(CustomQuoteRule, rule_id)
        rule.unit_price = 999
        rule.data_version = "surface-price-v4"
        rule.record_version = 4
        db.commit()
    assert client.post(url + "/quotes", headers=headers, json=payload).json()["snapshot"] == snapshot
    updated = client.post(
        url + "/quotes",
        headers=headers,
        json={**payload, "client_mutation_id": "material-v4"},
    ).json()["snapshot"]
    assert updated["lines"][0]["source_version"] == 4
    assert updated["lines"][0]["source_data_version"] == "surface-price-v4"
    assert updated["lines"][0]["rule_evidence"]["recordVersion"] == 4
    assert updated["content_digest"] != snapshot["content_digest"]


@pytest.mark.parametrize(
    ("rule_update", "reason"),
    [
        ({"is_active": False}, "quote_rule_inactive"),
        ({"region_codes": ["CN-BJ"]}, "quote_rule_region_mismatch"),
        ({"pricing_unit": "延米"}, "quote_rule_unit_unsupported"),
        ({"data_version": ""}, "quote_rule_version_invalid"),
    ],
)
def test_surface_rule_not_applicable_stays_pending(assets_context, rule_update, reason):
    client, factory, url, headers, _ = prepare(assets_context)
    with factory() as db:
        space = db.query(DesignSpaceVersion).filter_by(
            task_id=int(url.split("/")[-2]), version=1
        ).one()
        document_json = deepcopy(space.document_json)
        document_json["scale_status"] = "confirmed"
        space.document_json = document_json
        rule = CustomQuoteRule(
            project_name="墙面材料",
            category="墙面材料",
            pricing_unit="㎡",
            material_grade="标准",
            unit_price=80,
            region_codes=["CN-SH"],
            data_version="material-v1",
            record_version=1,
            is_active=True,
        )
        for key, value in rule_update.items():
            setattr(rule, key, value)
        db.add(rule)
        db.commit()
        rule_id = rule.id
    current = client.get(url, headers=headers).json()["document"]
    current["surfaces"] = [{
        "id": "floor", "room_id": "r1", "kind": "floor",
        "material": {"name": "同名不应回退匹配", "color": "#eeeeee"},
        "quote_rule_id": rule_id,
    }]
    assert client.put(url, headers=headers, json={
        "base_version": 1, "client_mutation_id": f"surface-{reason}", "document": current,
    }).status_code == 200
    quote = client.post(url + "/quotes", headers=headers, json={
        "home_version": 2, "region": "CN-SH", "client_mutation_id": f"quote-{reason}",
    }).json()["snapshot"]
    line = next(item for item in quote["lines"] if item["id"] == "floor")
    assert line["unit_price"] is None and line["total_price"] is None
    assert line["reasons"] == [reason]
    assert line["rule_evidence"] is None
    assert quote["total_price"] is None


def test_surface_without_rule_or_confirmed_scale_never_becomes_zero(assets_context):
    client, _, url, headers, _ = prepare(assets_context)
    current = client.get(url, headers=headers).json()["document"]
    current["surfaces"] = [{
        "id": "floor", "room_id": "r1", "kind": "floor",
        "material": {"name": "未绑定材料", "color": "#eeeeee"},
    }]
    assert client.put(url, headers=headers, json={
        "base_version": 1, "client_mutation_id": "no-rule", "document": current,
    }).status_code == 200
    quote = client.post(url + "/quotes", headers=headers, json={
        "home_version": 2, "region": "CN-SH", "client_mutation_id": "no-rule-quote",
    }).json()["snapshot"]
    line = next(item for item in quote["lines"] if item["id"] == "floor")
    assert line["quantity"] is None
    assert line["reasons"] == ["surface_scale_unconfirmed", "quote_rule_required"]
    assert quote["known_subtotal"] == 100
    assert quote["pending_count"] == 1
    assert quote["total_price"] is None


def test_global_surface_rule_and_repeated_fees_are_applied_per_surface(assets_context):
    client, factory, url, headers, _ = prepare(assets_context)
    with factory() as db:
        space = db.query(DesignSpaceVersion).filter_by(
            task_id=int(url.split("/")[-2]), version=1
        ).one()
        document_json = deepcopy(space.document_json)
        document_json["scale_status"] = "confirmed"
        space.document_json = document_json
        rule = CustomQuoteRule(
            project_name="全局地面材料",
            category="地面材料",
            pricing_unit="㎡",
            material_grade="标准",
            unit_price=100,
            region_codes=[],
            installation_fee=20,
            shipping_fee=10,
            data_version="global-v1",
            record_version=1,
            is_active=True,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id
    current = client.get(url, headers=headers).json()["document"]
    current["objects"] = []
    current["surfaces"] = [
        {
            "id": kind,
            "room_id": "r1",
            "kind": kind,
            "material": {"name": "全局规则", "color": "#eeeeee"},
            "quote_rule_id": rule_id,
        }
        for kind in ("floor", "ceiling")
    ]
    assert client.put(
        url,
        headers=headers,
        json={"base_version": 1, "client_mutation_id": "global-rule", "document": current},
    ).status_code == 200

    snapshot = client.post(
        url + "/quotes",
        headers=headers,
        json={
            "home_version": 2,
            "region": "CN-BJ",
            "client_mutation_id": "global-rule-quote",
        },
    ).json()["snapshot"]

    assert [line["total_price"] for line in snapshot["lines"]] == [1230, 1230]
    assert snapshot["known_subtotal"] == 2460
    assert snapshot["pending_count"] == 0
    assert all(line["rule_evidence"]["ruleRegionCodes"] == [] for line in snapshot["lines"])
    assert any("逐行计算" in limitation for limitation in snapshot["limitations"])


@pytest.mark.parametrize(
    "update",
    [
        {"home_version": True},
        {"region": "cn-sh"},
        {"unit_price": 1},
        {"region": "*"},
        {"client_mutation_id": " "},
    ],
)
def test_request_cannot_supply_money_or_invalid_scope(assets_context, update):
    client, _, url, headers, _ = prepare(assets_context)
    result = client.post(
        url + "/quotes",
        headers=headers,
        json={
            "home_version": 1,
            "region": "CN-SH",
            "client_mutation_id": "invalid",
            **update,
        },
    )
    assert result.status_code == 422


def test_parent_lock_busy_is_retryable_conflict(assets_context, monkeypatch):
    from app.services import home_quote_service
    from app.services.aggregate_lock_service import AggregateLockBusy

    client, _, url, headers, _ = prepare(assets_context)

    def busy(*args, **kwargs):
        raise AggregateLockBusy("busy")

    monkeypatch.setattr(home_quote_service, "lock_owned_task", busy)
    result = client.post(
        url + "/quotes",
        headers=headers,
        json={"home_version": 1, "region": "CN-SH", "client_mutation_id": "busy"},
    )
    assert result.status_code == 409


def test_same_key_concurrent_freezes_only_one_row(assets_context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select, func
    from app.schemas.home_quote import HomeQuoteRequest
    from app.services.home_quote_service import create_quote

    _, factory, url, headers, _ = prepare(assets_context)
    task_id = int(url.split("/")[-2])
    gate = Barrier(2)

    def run():
        with factory() as db:
            gate.wait(timeout=10)
            return create_quote(
                db,
                task_id=task_id,
                session_id=headers["X-Session-Id"],
                payload=HomeQuoteRequest(
                    home_version=1, region="CN-SH", client_mutation_id="same"
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(HomeDesignQuote)) == 1


def test_quote_expired_price_and_asset_digest(assets_context):
    client, factory, url, headers, product_id = prepare(assets_context)
    delivery = client.get(url + "/versions/1/delivery", headers=headers).json()
    payload = {"home_version": 1, "region": "CN-SH", "client_mutation_id": "first"}
    frozen = client.post(url + "/quotes", headers=headers, json=payload).json()[
        "snapshot"
    ]
    assert frozen["task_id"] == int(url.split("/")[-2])
    assert frozen["delivery_digest"] == delivery["content_digest"]
    assert (
        frozen["lines"][0]["asset_digest"]
        == delivery["lines"][0]["asset"]["content_digest"]
    )
    with factory() as db:
        db.get(Product, product_id).price_valid_to = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.commit()
    pending = client.post(
        url + "/quotes",
        headers=headers,
        json={**payload, "client_mutation_id": "expired"},
    ).json()["snapshot"]
    assert "price_expired" in pending["lines"][0]["reasons"]
    assert pending["total_price"] is None


def test_quote_migration_upgrade_downgrade():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.db.database import Base

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/migrations/versions/e5f6a7b8c9d0_add_home_quotes.py"
    )
    spec = importlib.util.spec_from_file_location("quote_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = inspect(connection)
            assert {
                c["name"] for c in inspector.get_columns("home_design_quotes")
            } == set(Base.metadata.tables["home_design_quotes"].columns.keys())
            assert inspector.get_unique_constraints("home_design_quotes")[0][
                "column_names"
            ] == ["task_id", "client_mutation_id"]
            migration.downgrade()
            assert "home_design_quotes" not in inspect(connection).get_table_names()
    engine.dispose()
