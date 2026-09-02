"""失败分诊报告的规范化 HMAC 签名。"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any


def _canonical_payload(payload: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validated_key(signing_key: str) -> bytes:
    encoded = signing_key.encode("utf-8")
    if len(encoded) < 32:
        raise ValueError("评测报告签名密钥至少需要 32 字节")
    return encoded


def sign_failure_triage_payload(
    payload: Mapping[str, Any],
    *,
    signing_key: str,
) -> str:
    return hmac.new(
        _validated_key(signing_key),
        _canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()


def verify_failure_triage_signature(
    payload: Mapping[str, Any],
    *,
    signing_key: str,
) -> bool:
    signature = payload.get("signature")
    if not isinstance(signature, str):
        return False
    try:
        expected = sign_failure_triage_payload(payload, signing_key=signing_key)
    except ValueError:
        return False
    return hmac.compare_digest(signature.lower(), expected)
