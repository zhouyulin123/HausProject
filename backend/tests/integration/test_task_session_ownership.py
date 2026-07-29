import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.tasks import create_task
from app.db.database import Base
from app.db.models import UploadedImage
from app.schemas.tasks import TaskCreate
from app.services.anonymous_session_service import (
    attach_image,
    create_anonymous_session,
    session_owns_task,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.mark.integration
def test_create_task_links_owned_images_to_anonymous_session(db):
    session = create_anonymous_session(db)
    image = UploadedImage(file_name="room.png", file_url="/uploads/room.png")
    db.add(image)
    db.commit()
    attach_image(db, session.id, image.id)

    response = create_task(
        TaskCreate(
            session_id=session.id,
            image_ids=[image.id],
            requirement={"rooms": ["客厅"], "styles": ["现代简约"]},
        ),
        db,
    )

    db.refresh(image)
    assert image.task_id == response.task_id
    assert session_owns_task(db, session.id, response.task_id)


@pytest.mark.integration
def test_create_task_rejects_images_owned_by_another_session(db):
    owner = create_anonymous_session(db)
    attacker = create_anonymous_session(db)
    image = UploadedImage(file_name="room.png", file_url="/uploads/room.png")
    db.add(image)
    db.commit()
    attach_image(db, owner.id, image.id)

    with pytest.raises(HTTPException) as exc_info:
        create_task(
            TaskCreate(
                session_id=attacker.id,
                image_ids=[image.id],
                requirement={"rooms": ["客厅"]},
            ),
            db,
        )

    assert exc_info.value.status_code == 403
