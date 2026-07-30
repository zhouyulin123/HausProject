import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import chat, proposal, render
from app.db.database import Base, get_db
from app.db.models import DesignTask
from app.services.anonymous_session_service import (
    attach_task,
    create_anonymous_session,
)


@pytest.fixture
def design_access_context(monkeypatch):
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
        db.commit()
        attach_task(db, owner.id, task.id)
        stranger_id = stranger.id
        task_id = task.id

    monkeypatch.setattr(
        chat.llm_service,
        "chat_reply",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("越权聊天不应调用模型")
        ),
    )
    monkeypatch.setattr(
        render.sd_service,
        "is_available",
        lambda: (_ for _ in ()).throw(
            AssertionError("越权绘图不应检查或调用 SD")
        ),
    )
    monkeypatch.setattr(
        proposal.pdf_service,
        "build_proposal_pdf",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("越权导出不应生成 PDF")
        ),
    )

    app = FastAPI()
    app.include_router(chat.router, prefix="/api/design/chat")
    app.include_router(render.router, prefix="/api/design/render")
    app.include_router(proposal.router, prefix="/api/design")

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, stranger_id, task_id


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/design/chat",
            {"message": "继续优化", "task_id": 1},
        ),
        (
            "/api/design/render",
            {"plan_id": "plan-a", "style": "奶油风", "task_id": 1},
        ),
        (
            "/api/design/proposal-pdf",
            {"plan": {"id": "plan-a", "name": "测试方案"}, "task_id": 1},
        ),
    ],
)
def test_design_resources_reject_foreign_task_before_external_calls(
    design_access_context,
    path: str,
    body: dict,
):
    client, stranger_id, task_id = design_access_context
    body["task_id"] = task_id

    response = client.post(
        path,
        headers={"X-Session-ID": stranger_id},
        json=body,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "设计任务不存在或不属于当前会话"


@pytest.mark.integration
def test_chat_requires_anonymous_session_header(design_access_context):
    client, _, task_id = design_access_context

    response = client.post(
        "/api/design/chat",
        json={"message": "继续优化", "task_id": task_id},
    )

    assert response.status_code == 422
