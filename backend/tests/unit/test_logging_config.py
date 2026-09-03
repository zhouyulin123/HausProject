from __future__ import annotations

import io
import json
import logging

from app.core.logging_config import JsonLogFormatter
from app.core.request_context import bind_request_id


def _render_log(*, message: str, extra: dict | None = None) -> dict:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("tests.structured-log")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info(message, extra=extra or {})
    finally:
        logger.handlers = []
        logger.propagate = True
    return json.loads(stream.getvalue())


def test_json_log_formatter_emits_request_context_and_allowlisted_fields():
    with bind_request_id("customer-trace-001"):
        payload = _render_log(
            message="request completed",
            extra={
                "event": "http_request_completed",
                "http_method": "GET",
                "http_path": "/ready",
                "status_code": 200,
                "duration_ms": 12.345,
                "secret_token": "must-not-be-serialized",
            },
        )

    assert payload["timestamp"].endswith("Z")
    assert payload["level"] == "INFO"
    assert payload["logger"] == "tests.structured-log"
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "customer-trace-001"
    assert payload["event"] == "http_request_completed"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/ready"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.345
    assert "secret_token" not in payload


def test_json_log_formatter_omits_missing_request_id_and_formats_exception():
    try:
        raise ValueError("structured failure")
    except ValueError:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonLogFormatter())
        logger = logging.getLogger("tests.structured-error")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.ERROR)
        try:
            logger.exception("operation failed", extra={"event": "worker_failed"})
        finally:
            logger.handlers = []
            logger.propagate = True

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "worker_failed"
    assert payload["exception_type"] == "ValueError"
    assert "structured failure" in payload["exception"]
    assert "request_id" not in payload
