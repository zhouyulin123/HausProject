"""Scene Agent 的进程内滑动窗口限流。

本地单进程部署可直接使用；多实例生产部署应替换为 Redis 等共享限流器。
"""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic


class SceneAgentRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("限流参数必须为正整数")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._accepted_request_ids: dict[str, dict[str, float]] = {}
        self._lock = Lock()
        self._checks = 0

    def retry_after(
        self,
        key: str,
        *,
        request_id: str | None = None,
        now: float | None = None,
    ) -> int | None:
        """记录一次允许的请求；幂等重放与被拒绝请求不占用新额度。"""
        current = monotonic() if now is None else now
        cutoff = current - self._window_seconds
        with self._lock:
            self._checks += 1
            if self._checks % 256 == 0:
                self._prune_stale_buckets(cutoff)

            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            accepted = self._accepted_request_ids.setdefault(key, {})
            stale_request_ids = [
                item_id
                for item_id, accepted_at in accepted.items()
                if accepted_at <= cutoff
            ]
            for item_id in stale_request_ids:
                del accepted[item_id]
            if request_id is not None and request_id in accepted:
                return None

            if len(bucket) >= self._max_requests:
                return max(1, ceil(bucket[0] + self._window_seconds - current))

            bucket.append(current)
            if request_id is not None:
                accepted[request_id] = current
            return None

    def _prune_stale_buckets(self, cutoff: float) -> None:
        stale_keys: list[str] = []
        for key, bucket in self._buckets.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                stale_keys.append(key)
        for key in stale_keys:
            del self._buckets[key]
            self._accepted_request_ids.pop(key, None)
