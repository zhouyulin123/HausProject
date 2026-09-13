"""开放几何入口共享的数据库滑动窗口限流。"""

from datetime import datetime, timezone
from math import ceil
from time import sleep

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AnonymousSessionTask, OpenGeometryRateLimitBucket


class OpenGeometryRateLimitError(RuntimeError):
    """共享限流状态不可被可靠读取或更新。"""


class OpenGeometryRateLimitScopeError(OpenGeometryRateLimitError):
    """会话与任务不是有效的所有权边界。"""


class OpenGeometryRateLimitStateError(OpenGeometryRateLimitError):
    """持久化限流状态损坏，禁止降级为进程内限流。"""


class OpenGeometryRateLimitContention(OpenGeometryRateLimitError):
    """数据库竞争持续超限，调用方应失败关闭。"""


class OpenGeometryRateLimiter:
    """通过数据库 CAS 在多个 API 实例之间共享精确滑动窗口。"""

    _max_cas_attempts = 32

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("限流参数必须为正整数")
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    def retry_after(
        self,
        db: Session,
        *,
        session_id: str,
        task_id: int,
        now: datetime | None = None,
    ) -> int | None:
        """原子记录一次尝试，达到限额时返回需要等待的秒数。"""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("限流时间必须包含时区")
        current_ms = int(current.timestamp() * 1000)

        for attempt in range(self._max_cas_attempts):
            self._assert_owned_scope(db, session_id=session_id, task_id=task_id)
            bucket = db.scalar(
                select(OpenGeometryRateLimitBucket).where(
                    OpenGeometryRateLimitBucket.session_id == session_id,
                    OpenGeometryRateLimitBucket.task_id == task_id,
                )
            )
            if bucket is None:
                db.add(
                    OpenGeometryRateLimitBucket(
                        session_id=session_id,
                        task_id=task_id,
                        attempted_at_json=[current_ms],
                        record_version=1,
                    )
                )
                try:
                    db.commit()
                    return None
                except IntegrityError:
                    db.rollback()
                    self._wait_for_competing_transaction(attempt)
                    continue
                except OperationalError as exc:
                    if not self._is_transient_lock_error(exc):
                        raise
                    db.rollback()
                    self._wait_for_competing_transaction(attempt)
                    continue

            timestamps = self._validated_timestamps(bucket)
            # 多实例机器时钟可能轻微回拨；桶内逻辑时间必须保持单调，
            # 否则会写出乱序状态，并在下一次请求时被误判为数据损坏。
            logical_current_ms = max(
                current_ms,
                timestamps[-1] if timestamps else current_ms,
            )
            cutoff_ms = logical_current_ms - self._window_seconds * 1000
            active = [value for value in timestamps if value > cutoff_ms]
            if len(active) >= self._max_requests:
                return max(
                    1,
                    ceil(
                        (
                            active[0]
                            + self._window_seconds * 1000
                            - logical_current_ms
                        )
                        / 1000
                    ),
                )

            next_timestamps = [*active, logical_current_ms]
            try:
                result = db.execute(
                    update(OpenGeometryRateLimitBucket)
                    .where(
                        OpenGeometryRateLimitBucket.id == bucket.id,
                        OpenGeometryRateLimitBucket.record_version
                        == bucket.record_version,
                    )
                    .values(
                        attempted_at_json=next_timestamps,
                        record_version=bucket.record_version + 1,
                        updated_at=current,
                    )
                    .execution_options(synchronize_session=False)
                )
            except OperationalError as exc:
                if not self._is_transient_lock_error(exc):
                    raise
                db.rollback()
                self._wait_for_competing_transaction(attempt)
                continue
            if result.rowcount == 1:
                try:
                    db.commit()
                    return None
                except OperationalError as exc:
                    if not self._is_transient_lock_error(exc):
                        raise
                    db.rollback()
                    self._wait_for_competing_transaction(attempt)
                    continue
            db.rollback()
            self._wait_for_competing_transaction(attempt)

        raise OpenGeometryRateLimitContention(
            "开放几何共享限流状态持续发生并发竞争"
        )

    @staticmethod
    def _assert_owned_scope(
        db: Session,
        *,
        session_id: str,
        task_id: int,
    ) -> None:
        ownership = db.get(AnonymousSessionTask, (session_id, task_id))
        if ownership is None:
            raise OpenGeometryRateLimitScopeError(
                "开放几何限流会话与任务边界无效"
            )

    @staticmethod
    def _validated_timestamps(bucket: OpenGeometryRateLimitBucket) -> list[int]:
        raw = bucket.attempted_at_json
        if (
            not isinstance(raw, list)
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in raw
            )
            or raw != sorted(raw)
            or not isinstance(bucket.record_version, int)
            or isinstance(bucket.record_version, bool)
            or bucket.record_version < 1
        ):
            raise OpenGeometryRateLimitStateError(
                "开放几何共享限流状态无效"
            )
        return raw

    @staticmethod
    def _is_transient_lock_error(exc: OperationalError) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "database is locked",
                "deadlock",
                "lock wait timeout",
            )
        )

    @staticmethod
    def _wait_for_competing_transaction(attempt: int) -> None:
        sleep(min(0.001 * (attempt + 1), 0.02))


open_geometry_rate_limiter = OpenGeometryRateLimiter(
    max_requests=settings.scene_agent_requests_per_minute,
    window_seconds=60,
)
