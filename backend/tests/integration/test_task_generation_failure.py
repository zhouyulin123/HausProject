import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks as task_routes
from app.db.database import Base
from app.db.models import DesignTask


@pytest.mark.integration
def test_generate_design_persists_failed_status(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        task = DesignTask(
            status="confirmed",
            progress=50,
            confirmed_requirement_json={
                "rooms": ["客厅"],
                "budgetRange": "8-15 万",
                "styles": ["现代简约"],
            },
        )
        db.add(task)
        db.commit()

        monkeypatch.setattr(
            task_routes.catalog_service,
            "build_catalog_context",
            lambda _: (_ for _ in ()).throw(RuntimeError("商品库暂时不可用")),
        )

        with pytest.raises(HTTPException) as exc_info:
            task_routes.generate_design(task.id, db)

        db.refresh(task)
        assert exc_info.value.status_code == 500
        assert task.status == "failed"
        assert task.progress == 0
        assert "商品库暂时不可用" in (task.error_message or "")
