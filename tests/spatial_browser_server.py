"""浏览器隔离验收服务：真实空间路由与临时 SQLite，不连接业务数据库。"""

import argparse
from pathlib import Path
import tempfile

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from app.api.routes import spatial
from app.db.database import Base, get_db
from app.db.models import DesignTask, UploadedImage
from app.services.anonymous_session_service import create_anonymous_session, attach_task


def create_app():
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs" / "v2-spatial-browser"
    output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="db-", dir=output)
    engine = create_engine(
        f"sqlite+pysqlite:///{Path(temporary.name).as_posix()}/test.sqlite",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = create_anonymous_session(db)
        task = DesignTask(status="waiting_input")
        db.add(task)
        db.flush()
        attach_task(db, session_id=owner.id, task_id=task.id)
        image = UploadedImage(
            task_id=task.id,
            file_url="/uploads/spatial-source.png",
            file_name="原始户型图.png",
        )
        db.add(image)
        db.commit()
        fixture = {"task_id": task.id, "session_id": owner.id, "image_id": image.id}
    app = FastAPI()
    app.state.temporary = temporary
    app.state.engine = engine

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.include_router(spatial.router, prefix="/api/design/tasks")

    @app.get("/fixture")
    def get_fixture():
        return fixture

    @app.post("/fixture")
    def new_fixture():
        with factory() as db:
            task = DesignTask(status="waiting_input")
            db.add(task)
            db.flush()
            attach_task(db, session_id=fixture["session_id"], task_id=task.id)
            image = UploadedImage(
                task_id=task.id,
                file_url="/uploads/spatial-source.png",
                file_name="原始户型图.png",
            )
            db.add(image)
            alternate = UploadedImage(
                task_id=task.id,
                file_url="/uploads/spatial-source.png",
                file_name="修订户型图.png",
            )
            db.add(alternate)
            db.commit()
            return {
                "task_id": task.id,
                "session_id": fixture["session_id"],
                "image_id": image.id,
                "alternate_image_id": alternate.id,
            }

    @app.get("/uploads/spatial-source.png")
    def source():
        return FileResponse(root / "case_image" / "户型图1.png")

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8083)
    arguments = parser.parse_args()
    uvicorn.run(
        create_app(), host="127.0.0.1", port=arguments.port, log_level="warning"
    )
