"""API 与 Worker 共用的结构化 JSON 日志配置。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import TextIO

from app.core.request_context import current_request_id


_STRUCTURED_FIELDS = (
    "event",
    "http_method",
    "http_path",
    "status_code",
    "duration_ms",
    "task_id",
    "run_id",
    "job_id",
    "worker_id",
    "worker_attempt",
    "exit_reason",
)


class JsonLogFormatter(logging.Formatter):
    """输出稳定字段并仅接受显式白名单扩展，避免意外记录凭据。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or current_request_id()
        if request_id:
            payload["request_id"] = str(request_id)
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


def configure_logging(
    *,
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
) -> None:
    """为独立进程安装单一 JSON handler。"""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

