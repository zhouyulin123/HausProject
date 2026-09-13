"""异步 Worker 进程级心跳与 API 就绪判断。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import WorkerHeartbeat


logger = logging.getLogger(__name__)
REQUIRED_WORKER_TYPES = ("generation", "effect_render", "blender")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_identity(*, worker_type: str, worker_id: str) -> None:
    if worker_type not in REQUIRED_WORKER_TYPES:
        raise ValueError("worker_type 不受支持")
    if not worker_id.strip() or len(worker_id) > 200:
        raise ValueError("worker_id 必须为 1 到 200 个字符")


def record_heartbeat(
    db: Session,
    *,
    worker_type: str,
    worker_id: str,
    now: datetime | None = None,
) -> WorkerHeartbeat:
    _validate_identity(worker_type=worker_type, worker_id=worker_id)
    recorded_at = _as_utc(now or _utc_now())
    heartbeat = db.scalar(
        select(WorkerHeartbeat).where(
            WorkerHeartbeat.worker_type == worker_type,
            WorkerHeartbeat.worker_id == worker_id,
        )
    )
    if heartbeat is None:
        heartbeat = WorkerHeartbeat(
            worker_type=worker_type,
            worker_id=worker_id,
            started_at=recorded_at,
            heartbeat_at=recorded_at,
        )
        db.add(heartbeat)
    else:
        heartbeat.heartbeat_at = recorded_at
        heartbeat.stopped_at = None
    db.commit()
    db.refresh(heartbeat)
    return heartbeat


def mark_stopped(
    db: Session,
    *,
    worker_type: str,
    worker_id: str,
    now: datetime | None = None,
) -> bool:
    _validate_identity(worker_type=worker_type, worker_id=worker_id)
    heartbeat = db.scalar(
        select(WorkerHeartbeat).where(
            WorkerHeartbeat.worker_type == worker_type,
            WorkerHeartbeat.worker_id == worker_id,
        )
    )
    if heartbeat is None:
        return False
    heartbeat.stopped_at = _as_utc(now or _utc_now())
    db.commit()
    return True


@dataclass(frozen=True)
class WorkerReadinessCheck:
    status: str
    active_workers: int
    last_heartbeat_at: datetime | None
    stale_after_seconds: int


@dataclass(frozen=True)
class WorkerReadinessSnapshot:
    ready: bool
    checks: dict[str, WorkerReadinessCheck]


def readiness_snapshot(
    db: Session,
    *,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> WorkerReadinessSnapshot:
    checked_at = _as_utc(now or _utc_now())
    cutoff = checked_at - timedelta(seconds=stale_after_seconds)
    rows = db.scalars(
        select(WorkerHeartbeat).where(
            WorkerHeartbeat.worker_type.in_(REQUIRED_WORKER_TYPES),
            WorkerHeartbeat.stopped_at.is_(None),
        )
    ).all()
    checks: dict[str, WorkerReadinessCheck] = {}
    for worker_type in REQUIRED_WORKER_TYPES:
        type_rows = [row for row in rows if row.worker_type == worker_type]
        latest = max(
            (_as_utc(row.heartbeat_at) for row in type_rows),
            default=None,
        )
        fresh_count = sum(
            1 for row in type_rows if _as_utc(row.heartbeat_at) >= cutoff
        )
        status = "ok" if fresh_count else ("stale" if latest else "missing")
        checks[worker_type] = WorkerReadinessCheck(
            status=status,
            active_workers=fresh_count,
            last_heartbeat_at=latest,
            stale_after_seconds=stale_after_seconds,
        )
    return WorkerReadinessSnapshot(
        ready=all(check.status == "ok" for check in checks.values()),
        checks=checks,
    )


class WorkerPresenceReporter:
    """在独立线程登记空闲及繁忙 Worker 的进程级存活状态。"""

    def __init__(
        self,
        *,
        worker_type: str,
        worker_id: str,
        heartbeat_seconds: int,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        _validate_identity(worker_type=worker_type, worker_id=worker_id)
        self.worker_type = worker_type
        self.worker_id = worker_id
        self.heartbeat_seconds = heartbeat_seconds
        self.session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _record(self) -> None:
        with self.session_factory() as db:
            record_heartbeat(
                db,
                worker_type=self.worker_type,
                worker_id=self.worker_id,
            )

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self._record()
            except Exception:
                logger.exception(
                    "Worker 存活心跳写入失败: type=%s",
                    self.worker_type,
                )

    def __enter__(self) -> "WorkerPresenceReporter":
        # 首次登记失败时拒绝进入消费循环，避免任务有消费者但就绪状态不可观测。
        self._record()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"{self.worker_type}-presence-heartbeat",
        )
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(5, self.heartbeat_seconds + 1))
        try:
            with self.session_factory() as db:
                mark_stopped(
                    db,
                    worker_type=self.worker_type,
                    worker_id=self.worker_id,
                )
        except Exception:
            logger.exception(
                "Worker 停止状态写入失败: type=%s",
                self.worker_type,
            )
