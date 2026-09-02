"""HTTP、Worker 与供应商调用共用的请求关联上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import re
from typing import Iterator
from uuid import uuid4


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def normalize_request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def current_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def bind_request_id(request_id: str | None) -> Iterator[str | None]:
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)
