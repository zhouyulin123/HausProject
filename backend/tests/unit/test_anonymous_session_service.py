from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import DesignTask, UploadedImage
from app.services.anonymous_session_service import (
    attach_image,
    attach_task,
    create_anonymous_session,
    get_active_session,
    session_owns_images,
    session_owns_task,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.mark.unit
def test_create_and_resume_anonymous_session(db):
    now = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)

    session = create_anonymous_session(db, now=now, ttl_days=30)
    resumed = get_active_session(db, session.id, now=now + timedelta(days=1))

    assert len(session.id) == 36
    assert resumed is not None
    assert resumed.id == session.id
    assert resumed.expires_at == now + timedelta(days=30)


@pytest.mark.unit
def test_expired_anonymous_session_cannot_resume(db):
    now = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    session = create_anonymous_session(db, now=now, ttl_days=1)

    resumed = get_active_session(db, session.id, now=now + timedelta(days=2))

    assert resumed is None


@pytest.mark.unit
def test_session_tracks_owned_images_and_tasks(db):
    session = create_anonymous_session(db)
    image = UploadedImage(file_name="room.png", file_url="/uploads/room.png")
    task = DesignTask(status="confirmed")
    db.add_all([image, task])
    db.commit()

    attach_image(db, session.id, image.id)
    attach_task(db, session.id, task.id)

    assert session_owns_images(db, session.id, [image.id])
    assert session_owns_task(db, session.id, task.id)
    assert not session_owns_images(db, session.id, [image.id, 9999])
    assert not session_owns_task(db, session.id, 9999)
