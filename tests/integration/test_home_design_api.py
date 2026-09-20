"""隔离数据库验证家装权限、不可变版本和并发契约。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import home_design
from app.db.database import get_db
from tests.integration.test_spatial_api import (
    context as spatial_context,  # noqa: F401
    request as space_request,
)
from tests.unit.test_home_design import document


@pytest.fixture
def context(spatial_context):  # noqa: F811
    spatial_client, factory, space_url, headers, stranger = spatial_context
    spatial_client.put(space_url, headers=headers, json=space_request())
    app = FastAPI()
    app.include_router(home_design.router, prefix="/api/design/tasks")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield (
            client,
            space_url.replace("/space", "/home-design"),
            headers,
            stranger,
            spatial_client,
            space_url,
        )


def payload(base=0, key="save"):
    return {"base_version": base, "client_mutation_id": key, "document": document()}


def test_history_idempotency_and_owned_reads(context):
    client, url, headers, stranger, spatial, space_url = context
    assert client.get(url, headers=headers).json()["version"] == 0
    first = client.put(url, headers=headers, json=payload())
    assert first.status_code == 200, first.text
    assert first.json()["validation"]["issues"][0]["code"] == "scale_unconfirmed"
    newer = space_request(1, "space2")
    newer["document"]["scale_status"] = "confirmed"
    assert spatial.put(space_url, headers=headers, json=newer).status_code == 200
    second = payload(1, "save2")
    second["document"]["space_version"] = 2
    assert client.put(url, headers=headers, json=second).json()["validation"]["valid"]
    assert client.put(url, headers=headers, json=payload()).json() == first.json()
    assert client.get(url + "/versions/1", headers=headers).json() == first.json()
    page = client.get(url + "/versions?limit=1", headers=headers).json()
    assert page["next_before_version"] == 2
    assert (
        client.get(url + "/versions?before_version=2", headers=headers).json()[
            "versions"
        ][0]["version"]
        == 1
    )
    for suffix in ["", "/versions", "/versions/1"]:
        assert (
            client.get(url + suffix, headers={"X-Session-Id": stranger}).status_code
            == 404
        )
    assert (
        client.put(url, headers={"X-Session-Id": stranger}, json=payload()).status_code
        == 404
    )


def test_private_home_reads_disable_shared_caching_for_owner_and_stranger(context):
    client, url, headers, stranger, _, _ = context
    assert client.put(url, headers=headers, json=payload()).status_code == 200
    for suffix in (
        "",
        "/versions",
        "/versions/1",
        "/asset-options?kind=product",
        "/assets/999",
    ):
        for request_headers in (headers, {"X-Session-Id": stranger}):
            response = client.get(url + suffix, headers=request_headers)
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["vary"].lower() == "x-session-id"


def test_invalid_reference_does_not_advance_and_geometry_is_reported(context):
    client, url, headers, _, _, _ = context
    invalid = payload()
    invalid["document"]["space_version"] = 999
    assert client.put(url, headers=headers, json=invalid).status_code == 422
    invalid = payload()
    invalid["document"]["objects"][0]["room_id"] = "missing"
    assert (
        client.post(
            url + "/validate", headers=headers, json=invalid["document"]
        ).status_code
        == 422
    )
    assert client.get(url, headers=headers).json()["version"] == 0
    outside = payload()
    outside["document"]["objects"][0]["position"]["x"] = 99
    response = client.put(url, headers=headers, json=outside)
    assert response.status_code == 200
    assert "object_outside_room" in [
        i["code"] for i in response.json()["validation"]["issues"]
    ]
    assert (
        client.post(url + "/validate", headers=headers, json=outside["document"]).json()
        == response.json()["validation"]
    )


def test_conflict_and_concurrent_idempotency(context):
    client, url, headers, _, _, _ = context
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.put(url, headers=headers, json=payload()), range(2)
            )
        )
    assert [r.status_code for r in results] == [200, 200]
    changed = deepcopy(payload())
    changed["document"]["objects"][0]["name"] = "改名"
    assert client.put(url, headers=headers, json=changed).status_code == 409
    assert client.put(url, headers=headers, json=payload(0, "other")).status_code == 409


def test_different_concurrent_creates_append_only_one_version(context):
    client, url, headers, _, _, _ = context
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda key: client.put(url, headers=headers, json=payload(0, key)),
                ["first", "second"],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert len(client.get(url + "/versions", headers=headers).json()["versions"]) == 1
    assert client.get(url + "/versions/999", headers=headers).status_code == 404


def test_invalid_room_reference_save_is_atomic(context):
    client, url, headers, _, _, _ = context
    invalid = payload()
    invalid["document"]["objects"][0]["room_id"] = "another-task-room"
    assert client.put(url, headers=headers, json=invalid).status_code == 422
    assert client.get(url, headers=headers).json()["version"] == 0
    assert client.get(url + "/versions", headers=headers).json()["versions"] == []


def test_lock_rechecks_ownership_and_busy_is_retryable(context, monkeypatch):
    from app.services.aggregate_lock_service import AggregateLockBusy

    client, url, headers, _, _, _ = context
    with monkeypatch.context() as patch:
        patch.setattr(home_design.service, "lock_owned_task", lambda *a, **kw: None)
        assert client.put(url, headers=headers, json=payload()).status_code == 404

    def busy(*args, **kwargs):
        raise AggregateLockBusy("正在更新")

    with monkeypatch.context() as patch:
        patch.setattr(home_design.service, "lock_owned_task", busy)
        response = client.put(url, headers=headers, json=payload())
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "home_design_busy"
    assert client.get(url, headers=headers).json()["version"] == 0


def test_updates_race_and_restore_history_as_new_version(context):
    client, url, headers, _, _, _ = context
    first = client.put(url, headers=headers, json=payload()).json()
    candidates = [payload(1, "a"), payload(1, "b")]
    for index, candidate in enumerate(candidates):
        candidate["document"]["objects"][0]["name"] = f"物件 {index}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda p: client.put(url, headers=headers, json=p), candidates)
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    restore = payload(2, "restore")
    response = client.put(url, headers=headers, json=restore)
    assert response.json()["version"] == 3
    assert response.json()["document"] == first["document"]
    assert client.get(url + "/versions/1", headers=headers).json() == first


def test_validate_permissions_and_history_query_limits(context):
    client, url, headers, stranger, _, _ = context
    assert (
        client.post(
            url + "/validate", headers={"X-Session-Id": stranger}, json=document()
        ).status_code
        == 404
    )
    for query in ["limit=0", "limit=51", "before_version=0"]:
        assert (
            client.get(url + "/versions?" + query, headers=headers).status_code == 422
        )


def test_home_state_queries_use_mysql_current_reads(context):
    from sqlalchemy import event
    from sqlalchemy.dialects import mysql
    from sqlalchemy.orm import Session

    client, url, headers, _, _, _ = context
    statements = []

    def record(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(Session, "do_orm_execute", record)
    try:
        assert client.put(url, headers=headers, json=payload()).status_code == 200
    finally:
        event.remove(Session, "do_orm_execute", record)
    reads = [
        sql
        for sql in statements
        if any(
            f"FROM {table}" in sql
            for table in [
                "home_designs",
                "home_design_versions",
                "design_space_versions",
            ]
        )
    ]
    assert len(reads) == 3
    assert all("FOR UPDATE" in sql for sql in reads)


def test_home_design_migration_matches_models_and_rolls_back(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from app.db.database import Base
    from app.db.schema_readiness import expected_migration_heads

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/migrations/versions/b2c3d4e5f6a7_add_home_designs.py"
    )
    spec = importlib.util.spec_from_file_location("home_design_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert expected_migration_heads() == ("f6a7b8c9d0e1",)
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = inspect(connection)
            for table in ("home_designs", "home_design_versions"):
                assert {
                    column["name"] for column in inspector.get_columns(table)
                } == set(Base.metadata.tables[table].columns.keys())
            assert {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints("home_design_versions")
            } == {("task_id", "version"), ("task_id", "client_mutation_id")}
            migration.downgrade()
            assert "home_designs" not in inspect(connection).get_table_names()
    engine.dispose()


def test_dense_validation_is_bounded_persisted_and_replayable(context):
    client, url, headers, _, _, _ = context
    request = payload()
    request["document"]["objects"] = [
        dict(deepcopy(document()["objects"][0]), id=f"o{i}") for i in range(500)
    ]
    saved = client.put(url, headers=headers, json=request)
    assert saved.status_code == 200
    validation = saved.json()["validation"]
    assert not validation["valid"]
    assert len(validation["issues"]) == 201
    assert validation["issues"][-1]["code"] == "validation_issue_limit"
    assert client.put(url, headers=headers, json=request).json() == saved.json()


def test_space_version_is_bound_to_task_not_global_version_number(spatial_context):  # noqa: F811
    from app.db.models import DesignTask
    from app.services.anonymous_session_service import attach_task

    spatial, factory, space_url, headers, _ = spatial_context
    assert (
        spatial.put(space_url, headers=headers, json=space_request()).status_code == 200
    )
    with factory() as db:
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        attach_task(db, session_id=headers["X-Session-Id"], task_id=other.id)
        other_id = other.id
        db.commit()
    app = FastAPI()
    app.include_router(home_design.router, prefix="/api/design/tasks")

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        url = f"/api/design/tasks/{other_id}/home-design"
        assert client.put(url, headers=headers, json=payload()).status_code == 422
        assert client.get(url, headers=headers).json()["version"] == 0
