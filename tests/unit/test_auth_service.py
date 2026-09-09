from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.database import Base
from app.db.models import SmsCode, User
from app.services import auth_service

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.mark.unit
def test_send_sms_code_persists_and_returns_mock_code(db):
    code = auth_service.send_sms_code(db, "13800000000", now=T0)
    record = db.scalar(select(SmsCode).where(SmsCode.phone == "13800000000"))
    assert code == settings.sms_mock_code
    assert record is not None
    assert record.consumed is False


@pytest.mark.unit
def test_send_sms_code_throttles_within_window(db):
    auth_service.send_sms_code(db, "13800000000", now=T0)
    with pytest.raises(auth_service.AuthError):
        auth_service.send_sms_code(db, "13800000000", now=T0 + timedelta(seconds=30))
    auth_service.send_sms_code(db, "13800000000", now=T0 + timedelta(seconds=61))


@pytest.mark.unit
def test_login_or_register_creates_customer_on_first_login(db):
    auth_service.send_sms_code(db, "13800000001", now=T0)
    user = auth_service.login_or_register(db, "13800000001", settings.sms_mock_code, now=T0)
    assert user.role == "customer"
    assert user.phone_verified is True
    assert db.scalar(select(User).where(User.phone == "13800000001")) is not None


@pytest.mark.unit
def test_login_rejects_wrong_code(db):
    auth_service.send_sms_code(db, "13800000002", now=T0)
    with pytest.raises(auth_service.AuthError):
        auth_service.login_or_register(db, "13800000002", "000000", now=T0)


@pytest.mark.unit
def test_login_code_is_single_use(db):
    auth_service.send_sms_code(db, "13800000003", now=T0)
    auth_service.login_or_register(db, "13800000003", settings.sms_mock_code, now=T0)
    with pytest.raises(auth_service.AuthError):
        auth_service.login_or_register(db, "13800000003", settings.sms_mock_code, now=T0)


@pytest.mark.unit
def test_token_roundtrip(db):
    user = User(phone="13800000004", nickname="13800000004", role="factory", phone_verified=True)
    db.add(user)
    db.commit()
    token = auth_service.issue_token(user)
    payload = auth_service.decode_token(token)
    assert payload["sub"] == str(user.id)
    assert payload["role"] == "factory"


@pytest.mark.unit
def test_decode_token_rejects_garbage():
    with pytest.raises(auth_service.AuthError):
        auth_service.decode_token("not-a-jwt")


@pytest.mark.unit
def test_merge_anonymous_session_claims_tasks_and_images(db):
    from app.db.models import DesignTask, UploadedImage
    from app.services import anonymous_session_service

    session = anonymous_session_service.create_anonymous_session(db)
    task = DesignTask(status="completed")
    db.add(task)
    db.commit()
    anonymous_session_service.attach_task(db, session.id, task.id)

    image = UploadedImage(file_url="/uploads/x.png")
    db.add(image)
    db.commit()
    anonymous_session_service.attach_image(db, session.id, image.id)

    user = User(
        phone="13800000005",
        nickname="13800000005",
        role="customer",
        phone_verified=True,
    )
    db.add(user)
    db.commit()

    merged = auth_service.merge_anonymous_session(db, session.id, user.id)
    db.refresh(task)
    db.refresh(image)
    assert merged == 1
    assert task.user_id == user.id
    assert image.user_id == user.id
