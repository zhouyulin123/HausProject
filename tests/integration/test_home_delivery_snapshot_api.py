"""冻结交付与受控分享的独立请求链路。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.api.main import api_router
from app.db.database import get_db
from tests.integration.test_spatial_api import context as spatial_context, request  # noqa: F401
from tests.unit.test_home_design import document


@pytest.fixture
def delivery_context(spatial_context):  # noqa: F811
    spatial, factory, space_url, headers, stranger = spatial_context
    spatial.put(space_url, headers=headers, json=request())
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        url = space_url.replace("/space", "/home-design")
        assert (
            client.put(
                url,
                headers=headers,
                json=dict(
                    base_version=0, client_mutation_id="save", document=document()
                ),
            ).status_code
            == 200
        )
        yield client, factory, url, headers, stranger


def test_snapshot_share_replay_and_revoke(delivery_context):
    client, _, url, headers, stranger = delivery_context
    payload = dict(home_version=1, client_mutation_id="delivery")
    result = client.post(url + "/deliveries", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert (
        client.post(url + "/deliveries", headers=headers, json=payload).json() == saved
    )
    assert (
        client.get(
            url + f"/deliveries/{saved['id']}", headers={"X-Session-Id": stranger}
        ).status_code
        == 404
    )
    path = url + f"/deliveries/{saved['id']}/shares"
    share = dict(
        client_mutation_id="share",
        consent_public=True,
        include_private_models=False,
        include_source_image=False,
        expires_in_hours=1,
    )
    created = client.post(path, headers=headers, json=share)
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    assert token
    assert client.post(path, headers=headers, json=share).json()["token"] is None
    public = client.get("/api/home-shares/" + token)
    assert public.status_code == 200, public.text
    assert "source_image_id" not in public.json()["snapshot"]["space"]
    assert "assets" not in public.json()["snapshot"]
    assert public.headers["cache-control"] == "no-store"
    assert (
        client.post(
            url + f"/shares/{created.json()['id']}/revoke", headers=headers
        ).status_code
        == 200
    )
    expired = client.get("/api/home-shares/" + token)
    assert expired.status_code == 404
    assert expired.headers["cache-control"] == "no-store"


def freeze(ctx, key="delivery"):
    client, _, url, headers, _ = ctx
    return client.post(
        url + "/deliveries",
        headers=headers,
        json=dict(home_version=1, client_mutation_id=key),
    )


def share(ctx, delivery_id, key="share"):
    client, _, url, headers, _ = ctx
    return client.post(
        url + f"/deliveries/{delivery_id}/shares",
        headers=headers,
        json=dict(client_mutation_id=key, consent_public=True),
    )


def test_confirmation_binding_list_and_idempotency(delivery_context):
    client, factory, url, headers, _ = delivery_context
    delivery = freeze(delivery_context).json()
    path = url + f"/deliveries/{delivery['id']}/confirmations"
    payload = dict(
        client_mutation_id="confirm",
        snapshot_digest=delivery["content_digest"],
        decision="reviewed",
        note="已审阅",
    )
    confirmed = client.post(path, headers=headers, json=payload)
    assert confirmed.status_code == 200, confirmed.text
    assert client.post(path, headers=headers, json=payload).json() == confirmed.json()
    assert client.get(path, headers=headers).json()["items"] == [confirmed.json()]
    listed = client.get(url + "/deliveries?home_version=1", headers=headers).json()[
        "items"
    ]
    assert listed == [
        {
            key: delivery[key]
            for key in (
                "id",
                "task_id",
                "home_version",
                "space_version",
                "quote_id",
                "content_digest",
                "created_at",
            )
        }
    ]
    assert "snapshot" not in listed[0]
    assert (
        client.get(url + "/deliveries?home_version=2", headers=headers).json()["items"]
        == []
    )
    payload["note"] = "另一次审阅"
    assert client.post(path, headers=headers, json=payload).status_code == 409
    payload["client_mutation_id"] = "bad-digest"
    payload["snapshot_digest"] = "0" * 64
    assert client.post(path, headers=headers, json=payload).status_code == 409
    from app.db.models import HomeDeliveryConfirmation

    with factory() as db:
        assert (
            db.query(HomeDeliveryConfirmation).one().actor_session_id
            == headers["X-Session-Id"]
        )


@pytest.mark.parametrize("mode", ["expired", "corrupt", "extra_private"])
def test_public_unavailable_on_expiry_or_damage(delivery_context, mode):
    from datetime import datetime, timedelta, timezone
    from app.db.models import HomeDeliveryShare
    from app.services.home_delivery_snapshot_service import digest

    client, factory, _, _, _ = delivery_context
    delivered = freeze(delivery_context).json()
    shared = share(delivery_context, delivered["id"]).json()
    with factory() as db:
        row = db.get(HomeDeliveryShare, shared["id"])
        if mode == "expired":
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        else:
            snapshot = dict(row.snapshot_json)
            snapshot["source_image_id"] = 22
            row.snapshot_json = snapshot
            if mode == "extra_private":
                row.content_digest = digest(snapshot)
        db.commit()
    result = client.get("/api/home-shares/" + shared["token"])
    assert result.status_code == 404, result.text
    assert result.headers["referrer-policy"] == "no-referrer"
    assert result.headers["x-robots-tag"] == "noindex, nofollow"


def test_rule_changes_do_not_change_frozen_delivery_or_share(
    delivery_context, monkeypatch
):
    from app.services import home_delivery_snapshot_service as service

    client, _, url, headers, _ = delivery_context
    delivered = freeze(delivery_context).json()
    shared = share(delivery_context, delivered["id"]).json()
    before = client.get("/api/home-shares/" + shared["token"]).json()

    def forbidden(*a, **kw):
        raise AssertionError("读取冻结快照不应重算")

    monkeypatch.setattr(service, "get_delivery", forbidden)
    assert freeze(delivery_context).json() == delivered
    assert (
        client.get(url + f"/deliveries/{delivered['id']}", headers=headers).json()
        == delivered
    )
    assert client.get("/api/home-shares/" + shared["token"]).json() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("consent_public", False),
        ("consent_public", 1),
        ("include_source_image", True),
        ("include_private_models", True),
    ],
)
def test_share_requires_explicit_supported_consent(delivery_context, field, value):
    client, _, url, headers, _ = delivery_context
    delivered = freeze(delivery_context).json()
    payload = dict(client_mutation_id="share", consent_public=True)
    payload[field] = value
    response = client.post(
        url + f"/deliveries/{delivered['id']}/shares", headers=headers, json=payload
    )
    assert response.status_code == 422


def test_private_asset_model_not_duplicated_and_public_projection_strips_sources(
    delivery_context, monkeypatch
):
    from app.services import home_delivery_snapshot_service as service

    client, _, url, headers, _ = delivery_context
    original = service.get_delivery

    def with_private(*args):
        value = original(*args)
        value["document"]["objects"][0]["asset_id"] = 8
        value["document"]["surfaces"].append(
            {
                "id": "priced-floor",
                "room_id": value["space"]["rooms"][0]["id"],
                "kind": "floor",
                "material": {"name": "white tile", "color": "#ffffff"},
                "quote_rule_id": 42,
            }
        )
        value["space"].update(
            source_image_id=99,
            image_reference=dict(origin=dict(x=0, z=0), width=4, depth=3),
        )
        value["assets"] = [
            dict(
                id=8,
                content_digest="a" * 64,
                kind="open_geometry",
                source_id=7,
                source_version=1,
                name="私有家具",
                model_spec={"secret": "x" * 6000000},
                source_summary={"path": "private"},
            )
        ]
        value["lines"][0]["asset"] = value["assets"][0]
        return value

    monkeypatch.setattr(service, "get_delivery", with_private)
    frozen = freeze(delivery_context)
    assert frozen.status_code == 200, frozen.text
    delivery = frozen.json()
    assert "model_spec" not in str(delivery)
    assert "source_summary" not in str(delivery)
    shared = share(delivery_context, delivery["id"]).json()
    public = client.get("/api/home-shares/" + shared["token"]).json()
    for forbidden in [
        "asset_id",
        "quote_rule_id",
        "source_image_id",
        "image_reference",
        "model_spec",
        "source_summary",
        "source_id",
        "private",
    ]:
        assert forbidden not in str(public)


def test_cross_task_and_quote_mismatch(delivery_context):
    from app.db.models import DesignTask, HomeDesignQuote
    from app.services.anonymous_session_service import attach_task
    from app.services.home_quote_service import digest

    client, factory, url, headers, _ = delivery_context
    delivered = freeze(delivery_context).json()
    with factory() as db:
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        attach_task(db, session_id=headers["X-Session-Id"], task_id=other.id)
        other_id = other.id
        snapshot = dict(
            schema_version="home-quote/1.0",
            task_id=1,
            home_version=2,
            space_version=1,
            delivery_digest="0" * 64,
        )
        snapshot["content_digest"] = digest(snapshot)
        quote = HomeDesignQuote(
            task_id=1,
            home_version=2,
            client_mutation_id="quote",
            request_digest="0" * 64,
            snapshot_json=snapshot,
        )
        db.add(quote)
        db.commit()
        quote_id = quote.id
    assert (
        client.get(
            f"/api/design/tasks/{other_id}/home-design/deliveries/{delivered['id']}",
            headers=headers,
        ).status_code
        == 404
    )
    result = client.post(
        url + "/deliveries",
        headers=headers,
        json=dict(home_version=1, quote_id=quote_id, client_mutation_id="mismatch"),
    )
    assert result.status_code == 409, result.text


def test_snapshot_corruption_and_pagination(delivery_context):
    from app.db.models import HomeDeliverySnapshot

    client, factory, url, headers, _ = delivery_context
    first = freeze(delivery_context).json()
    second = freeze(delivery_context, "second").json()
    page = client.get(url + "/deliveries?limit=1", headers=headers).json()
    assert page["next_before_id"] == second["id"]
    assert client.get(
        url + f"/deliveries?before_id={second['id']}", headers=headers
    ).json()["items"] == [
        {
            key: first[key]
            for key in (
                "id",
                "task_id",
                "home_version",
                "space_version",
                "quote_id",
                "content_digest",
                "created_at",
            )
        }
    ]
    with factory() as db:
        row = db.get(HomeDeliverySnapshot, first["id"])
        row.snapshot_json = {}
        db.commit()
    assert (
        client.get(url + f"/deliveries/{first['id']}", headers=headers).status_code
        == 409
    )
    listed = client.get(url + "/deliveries", headers=headers)
    assert listed.status_code == 200, listed.text
    assert first["id"] in {item["id"] for item in listed.json()["items"]}


def test_delivery_list_does_not_load_snapshot_json(delivery_context, monkeypatch):
    from app.services import home_delivery_snapshot_service as service

    client, _, url, headers, _ = delivery_context
    freeze(delivery_context)
    original = service.delivery_summary_response

    def inspect_loaded_columns(row):
        assert "snapshot_json" not in row.__dict__
        result = original(row)
        assert "snapshot_json" not in row.__dict__
        return result

    monkeypatch.setattr(service, "delivery_summary_response", inspect_loaded_columns)
    response = client.get(url + "/deliveries", headers=headers)
    assert response.status_code == 200, response.text


def test_delivery_list_is_bounded_for_multiple_near_limit_snapshots(delivery_context):
    from app.db.models import HomeDeliverySnapshot
    from app.services import home_delivery_snapshot_service as service

    client, factory, url, headers, stranger = delivery_context
    deliveries = [freeze(delivery_context, f"large-{index}").json() for index in range(3)]
    with factory() as db:
        for delivery in deliveries:
            row = db.get(HomeDeliverySnapshot, delivery["id"])
            snapshot = dict(row.snapshot_json)
            snapshot["limitations"] = [""]
            padding_size = service.MAX_BYTES - len(service.canonical(snapshot)) - 128
            snapshot["limitations"] = ["x" * padding_size]
            encoded_size = len(service.canonical(snapshot))
            assert service.MAX_BYTES - 256 < encoded_size <= service.MAX_BYTES
            row.snapshot_json = snapshot
            row.content_digest = service.digest(snapshot)
        db.commit()

    response = client.get(url + "/deliveries?limit=20", headers=headers)
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 3
    assert len(response.content) < 4096
    assert all("snapshot" not in item for item in response.json()["items"])
    assert (
        client.get(
            url + "/deliveries?limit=20", headers={"X-Session-Id": stranger}
        ).status_code
        == 404
    )


def test_exact_quote_binding_preserves_unknown_prices(delivery_context):
    client, _, url, headers, _ = delivery_context
    quote = client.post(
        url + "/quotes",
        headers=headers,
        json=dict(home_version=1, region="CN-11", client_mutation_id="quote"),
    )
    assert quote.status_code == 200, quote.text
    result = client.post(
        url + "/deliveries",
        headers=headers,
        json=dict(
            home_version=1, quote_id=quote.json()["id"], client_mutation_id="with-quote"
        ),
    )
    assert result.status_code == 200, result.text
    snapshot = result.json()["snapshot"]
    assert snapshot["quote"]["delivery_digest"] == snapshot["original_delivery_digest"]
    assert snapshot["quote"]["total_price"] is None
    public_share = share(delivery_context, result.json()["id"]).json()
    public = client.get("/api/home-shares/" + public_share["token"])
    assert public.status_code == 200, public.text
    assert public.json()["snapshot"]["quote"]["total_price"] is None
    assert public.json()["snapshot"]["quote"]["pending_count"] > 0


def test_snapshot_quota_checks_after_replay(delivery_context):
    from app.db.models import HomeDeliverySnapshot

    client, factory, url, headers, _ = delivery_context
    saved = freeze(delivery_context).json()
    with factory() as db:
        original = db.get(HomeDeliverySnapshot, saved["id"])
        for index in range(99):
            db.add(
                HomeDeliverySnapshot(
                    task_id=original.task_id,
                    home_version=1,
                    space_version=1,
                    client_mutation_id=f"quota-{index}",
                    request_digest="0" * 64,
                    snapshot_json=original.snapshot_json,
                    content_digest=original.content_digest,
                )
            )
        db.commit()
    assert freeze(delivery_context).json() == saved
    assert freeze(delivery_context, "over-quota").status_code == 409


def test_public_database_outage_is_sanitized(delivery_context, monkeypatch):
    from app.services import home_delivery_snapshot_service as service
    from sqlalchemy.exc import OperationalError

    client, _, _, _, _ = delivery_context

    def broken(*args):
        raise OperationalError("private SQL", {}, Exception("private detail"))

    monkeypatch.setattr(service, "public_share", broken)
    response = client.get("/api/home-shares/" + "a" * 43)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
