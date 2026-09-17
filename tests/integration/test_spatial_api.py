"""任务级空间 API 的隔离数据库验证。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import spatial
from app.db.database import Base, get_db
from app.db.models import DesignTask, DesignSpaceVersion, UploadedImage
from app.services.anonymous_session_service import create_anonymous_session, attach_task
from tests.unit.test_spatial_document import document


@pytest.fixture
def context(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'spatial.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(status="waiting_input")
        db.add(task)
        db.flush()
        attach_task(db, session_id=owner.id, task_id=task.id)
        db.commit()
        task_id, owner_id, stranger_id = task.id, owner.id, stranger.id
    app = FastAPI()
    app.include_router(spatial.router, prefix="/api/design/tasks")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield (
            client,
            factory,
            f"/api/design/tasks/{task_id}/space",
            {"X-Session-Id": owner_id},
            stranger_id,
        )
    engine.dispose()


def request(base=0, key="save-1"):
    return {"base_version": base, "client_mutation_id": key, "document": document()}


def test_save_restore_history_and_idempotency_before_cas(context):
    client, factory, url, headers, _ = context
    assert client.get(url, headers=headers).json() == {
        "task_id": 1,
        "version": 0,
        "document": None,
    }
    first = request()
    saved = client.put(url, headers=headers, json=first)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    second = request(1, "save-2")
    second["document"]["rooms"][0]["name"] = "新名字"
    assert client.put(url, headers=headers, json=second).json()["version"] == 2
    replay = client.put(url, headers=headers, json=first)
    assert replay.json() == saved.json()
    assert client.get(url, headers=headers).json()["version"] == 2
    with factory() as db:
        versions = db.scalars(
            select(DesignSpaceVersion).order_by(DesignSpaceVersion.version)
        ).all()
        assert len(versions) == 2
        assert versions[0].document_json["rooms"][0]["name"] == "房间"


def test_permissions_conflicts_invalid_geometry_and_source(context):
    client, _, url, headers, stranger = context
    first = request()
    assert client.put(url, headers=headers, json=first).status_code == 200
    assert client.get(url, headers={"X-Session-Id": stranger}).status_code == 404
    assert (
        client.put(url, headers={"X-Session-Id": stranger}, json=first).status_code
        == 404
    )
    changed = deepcopy(first)
    changed["document"]["rooms"][0]["name"] = "变更"
    assert client.put(url, headers=headers, json=changed).status_code == 409
    assert client.put(url, headers=headers, json=request(0, "other")).status_code == 409
    invalid = request(1, "invalid")
    invalid["document"]["rooms"][0]["polygon"][1] = {"x": 0, "z": 0}
    assert client.put(url, headers=headers, json=invalid).status_code == 422
    invalid_source = request(1, "source")
    invalid_source["document"]["source_image_id"] = 999
    assert client.put(url, headers=headers, json=invalid_source).status_code == 422
    assert client.get(url, headers=headers).json()["version"] == 1


def test_concurrent_first_save_serializes_on_parent(context):
    client, factory, url, headers, _ = context
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda key: client.put(url, headers=headers, json=request(0, key)),
                ["a", "b"],
            )
        )
    assert sorted(result.status_code for result in results) == [200, 409]
    with factory() as db:
        assert len(db.scalars(select(DesignSpaceVersion)).all()) == 1


def test_concurrent_identical_first_save_replays(context):
    client, _, url, headers, _ = context
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.put(url, headers=headers, json=request()), [1, 2])
        )
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json() == results[1].json()


def test_source_binding_rejects_other_tasks_but_accepts_owned_image(context):
    client, factory, url, headers, _ = context
    with factory() as db:
        other = DesignTask(status="waiting_input")
        db.add(other)
        db.flush()
        owned_image = UploadedImage(
            task_id=1, file_url="/uploads/owned.png", file_name="原图"
        )
        other_image = UploadedImage(
            task_id=other.id, file_url="/uploads/other.png", file_name="其他"
        )
        db.add_all([owned_image, other_image])
        db.commit()
        owned_id, other_id = owned_image.id, other_image.id
    payload = request()
    payload["document"]["source_image_id"] = other_id
    assert client.put(url, headers=headers, json=payload).status_code == 422
    payload["document"]["source_image_id"] = owned_id
    assert (
        client.put(url, headers=headers, json=payload).json()["document"][
            "source_image_id"
        ]
        == owned_id
    )


def test_unknown_task_and_missing_session_are_not_readable(context):
    client, _, _, headers, _ = context
    assert client.get("/api/design/tasks/999/space", headers=headers).status_code == 404
    assert client.get("/api/design/tasks/1/space").status_code == 422


def test_busy_lock_is_a_retryable_conflict(context, monkeypatch):
    from app.services.aggregate_lock_service import AggregateLockBusy

    client, _, url, headers, _ = context

    def busy(*args, **kwargs):
        raise AggregateLockBusy("正在更新")

    monkeypatch.setattr(spatial.spatial_service, "lock_owned_task", busy)
    result = client.put(url, headers=headers, json=request())
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "spatial_busy"


def test_ownership_is_rechecked_after_lock(context, monkeypatch):
    client, _, url, headers, _ = context
    monkeypatch.setattr(
        spatial.spatial_service, "lock_owned_task", lambda *args, **kwargs: None
    )
    assert client.put(url, headers=headers, json=request()).status_code == 404


def test_saved_state_queries_use_current_reads_after_parent_lock(context, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.dialects import mysql
    from sqlalchemy.orm import Session

    client, _, url, headers, _ = context
    statements = []

    def record(execute_state):
        if execute_state.is_select:
            statements.append(
                str(execute_state.statement.compile(dialect=mysql.dialect()))
            )

    event.listen(Session, "do_orm_execute", record)
    try:
        assert client.put(url, headers=headers, json=request()).status_code == 200
    finally:
        event.remove(Session, "do_orm_execute", record)
    reads = [
        sql
        for sql in statements
        if "FROM design_spaces" in sql or "FROM design_space_versions" in sql
    ]
    assert reads and all("FOR UPDATE" in sql for sql in reads)


def test_space_migration_and_readiness_are_consistent(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from app.db.schema_readiness import expected_migration_heads

    root = Path(__file__).resolve().parents[2]
    path = root / "backend/migrations/versions/a1b2c3d4e5f6_add_task_spaces.py"
    spec = importlib.util.spec_from_file_location("spatial_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert expected_migration_heads() == (migration.revision,)
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE design_tasks (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = inspect(connection)
            for table in ("design_spaces", "design_space_versions"):
                assert {col["name"] for col in inspector.get_columns(table)} == set(
                    Base.metadata.tables[table].columns.keys()
                )
            assert {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("design_space_versions")
            } == {("task_id", "version"), ("task_id", "client_mutation_id")}
            migration.downgrade()
            assert "design_spaces" not in inspect(connection).get_table_names()
    engine.dispose()
