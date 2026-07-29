from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnonymousSession,
    AnonymousSessionImage,
    AnonymousSessionTask,
    DesignTask,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_anonymous_session(
    db: Session,
    *,
    now: datetime | None = None,
    ttl_days: int = 30,
) -> AnonymousSession:
    current = now or _utc_now()
    session = AnonymousSession(
        id=str(uuid4()),
        status="active",
        created_at=current,
        last_seen_at=current,
        expires_at=current + timedelta(days=ttl_days),
    )
    db.add(session)
    db.commit()
    return session


def get_active_session(
    db: Session,
    session_id: str,
    *,
    now: datetime | None = None,
    touch: bool = True,
) -> AnonymousSession | None:
    session = db.get(AnonymousSession, session_id)
    if not session or session.status != "active":
        return None

    current = now or _utc_now()
    if _as_utc(session.expires_at) <= _as_utc(current):
        session.status = "expired"
        db.commit()
        return None

    if touch:
        session.last_seen_at = current
        db.commit()
    return session


def attach_image(db: Session, session_id: str, image_id: int) -> None:
    if not get_active_session(db, session_id):
        raise ValueError("匿名会话不存在或已过期")
    relation = db.get(
        AnonymousSessionImage,
        {"session_id": session_id, "image_id": image_id},
    )
    if not relation:
        db.add(AnonymousSessionImage(session_id=session_id, image_id=image_id))
        db.commit()


def attach_task(db: Session, session_id: str, task_id: int) -> None:
    if not get_active_session(db, session_id):
        raise ValueError("匿名会话不存在或已过期")
    relation = db.get(
        AnonymousSessionTask,
        {"session_id": session_id, "task_id": task_id},
    )
    if not relation:
        db.add(AnonymousSessionTask(session_id=session_id, task_id=task_id))
        db.commit()


def session_owns_images(db: Session, session_id: str, image_ids: list[int]) -> bool:
    unique_ids = set(image_ids)
    if not unique_ids:
        return True
    owned_count = db.scalar(
        select(func.count(AnonymousSessionImage.image_id)).where(
            AnonymousSessionImage.session_id == session_id,
            AnonymousSessionImage.image_id.in_(unique_ids),
        )
    )
    return owned_count == len(unique_ids)


def session_owns_task(db: Session, session_id: str, task_id: int) -> bool:
    return (
        db.get(
            AnonymousSessionTask,
            {"session_id": session_id, "task_id": task_id},
        )
        is not None
    )


def list_session_tasks(db: Session, session_id: str) -> list[DesignTask]:
    return list(
        db.scalars(
            select(DesignTask)
            .join(
                AnonymousSessionTask,
                AnonymousSessionTask.task_id == DesignTask.id,
            )
            .where(AnonymousSessionTask.session_id == session_id)
            .order_by(DesignTask.id.desc())
        )
    )
