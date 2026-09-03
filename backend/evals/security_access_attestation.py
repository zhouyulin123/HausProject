"""对受控部署执行真实 HTTP 跨会话访问检查并签发匿名证据。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from evals.real_world import (
    EvaluationInputError,
    EvaluationSplit,
    EvaluationVersions,
    RealWorldDataset,
    validate_evaluation_split,
)


SECURITY_EVIDENCE_SCHEMA_VERSION = "1.0"
SECURITY_EVIDENCE_TYPE = "cross_user_access_http"
SECURITY_SUITE_VERSION = "cross-user-http/1.0"
SECURITY_SIGNATURE_ALGORITHM = "HMAC-SHA256"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESOURCE_BINDING_PATTERN = re.compile(r"^resource-hmac-sha256:[0-9a-f]{64}$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_MAX_ATTESTATION_LIFETIME_SECONDS = 3600
_CLOCK_SKEW_SECONDS = 60


@dataclass(frozen=True)
class AccessTarget:
    case_id: str
    task_id: int
    foreign_control_task_id: int
    owner_session_env: str
    foreign_session_env: str


@dataclass(frozen=True)
class HttpObservation:
    status_code: int
    headers: Mapping[str, str]
    json_body: Any


class HttpTransport(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> HttpObservation: ...


@dataclass(frozen=True)
class SecurityCaseResult:
    case_fingerprint: str
    resource_binding_digest: str
    check_count: int
    severe_count: int
    owner_status: int
    foreign_status: int


@dataclass(frozen=True)
class VerifiedSecurityAccessAttestation:
    suite_version: str
    app_build_digest: str
    deployment_environment: str
    dataset_fingerprint: str
    split: EvaluationSplit
    versions: EvaluationVersions
    issued_at: datetime
    expires_at: datetime
    case_results: tuple[SecurityCaseResult, ...]
    check_count: int
    severe_count: int
    key_id: str
    evidence_digest: str


class UrllibHttpTransport:
    """生产 CLI 使用的最小只读 HTTP transport。"""

    def __init__(self, *, timeout_seconds: float = 10.0):
        if timeout_seconds <= 0:
            raise ValueError("HTTP 超时必须为正数")
        self.timeout_seconds = timeout_seconds

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None

        self._opener = build_opener(NoRedirect())

    def get(self, url: str, *, headers: dict[str, str]) -> HttpObservation:
        request = Request(url, method="GET", headers=headers)
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
        except HTTPError as exc:
            response = exc
        except URLError as exc:
            raise EvaluationInputError("安全回归 HTTP 请求失败") from exc
        try:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise EvaluationInputError("安全回归 HTTP 响应过大")
            try:
                body = json.loads(raw.decode("utf-8")) if raw else None
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvaluationInputError("安全回归 HTTP 响应不是合法 JSON") from exc
            response_headers = {
                str(key).lower(): str(value) for key, value in response.headers.items()
            }
            return HttpObservation(
                status_code=int(response.status),
                headers=response_headers,
                json_body=body,
            )
        finally:
            response.close()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvaluationInputError("安全证据包含不可序列化值") from exc


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def _sign(value: Mapping[str, Any], signing_key: str) -> str:
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise EvaluationInputError("安全证据签名密钥至少需要 32 字节")
    return "security-hmac-sha256:" + hmac.new(
        signing_key.encode("utf-8"),
        _canonical_json(value),
        hashlib.sha256,
    ).hexdigest()


def _case_fingerprint(dataset_digest: str, case_id: str) -> str:
    return _digest({"dataset_fingerprint": dataset_digest, "case_id": case_id})


def _resource_binding_digest(
    *,
    dataset_digest: str,
    case_digest: str,
    task_id: int,
    run_id: int,
    binding_key: str,
) -> str:
    payload = _canonical_json(
        {
            "domain": "cross-user-resource-binding/1.0",
            "dataset_fingerprint": dataset_digest,
            "case_fingerprint": case_digest,
            "task_id": task_id,
            "run_id": run_id,
        }
    )
    return "resource-hmac-sha256:" + hmac.new(
        binding_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def _dataset_digest(dataset: RealWorldDataset, split: EvaluationSplit) -> str:
    from evals.trusted_evidence import dataset_fingerprint

    return dataset_fingerprint(dataset, split=split)


def _validate_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise EvaluationInputError(f"{label} 必须是 SHA-256 摘要")


def _validate_versions(versions: EvaluationVersions) -> None:
    for field_name in ("prompt", "rules", "data"):
        _validate_digest(getattr(versions, field_name), f"{field_name} 版本")


def _header(observation: HttpObservation, name: str) -> str | None:
    lowered = name.lower()
    return next(
        (
            str(value)
            for key, value in observation.headers.items()
            if str(key).lower() == lowered
        ),
        None,
    )


def _assert_deployed_build(
    observation: HttpObservation,
    expected_build_digest: str,
) -> None:
    if _header(observation, "x-app-build-digest") != expected_build_digest:
        raise EvaluationInputError("受控部署返回的应用构建摘要不一致")


def _session_id(value: Any, *, env_name: str) -> str:
    if not isinstance(value, str):
        raise EvaluationInputError(f"缺少会话凭据环境变量：{env_name}")
    try:
        normalized = str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise EvaluationInputError(f"会话凭据环境变量不合法：{env_name}") from exc
    if normalized != value.lower():
        raise EvaluationInputError(f"会话凭据环境变量不合法：{env_name}")
    return normalized


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _request_headers(session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-store",
        "X-Request-ID": str(uuid4()),
    }
    if session_id is not None:
        headers["X-Session-ID"] = session_id
    return headers


def collect_security_access_attestation(
    *,
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    targets: tuple[AccessTarget, ...],
    versions: EvaluationVersions,
    base_url: str,
    app_build_digest: str,
    credentials: Mapping[str, str],
    transport: HttpTransport,
    signing_key: str,
    key_id: str,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """执行真实 HTTP 检查；计数只能由 HTTP 观察结果产生。"""
    normalized_split = validate_evaluation_split(split)
    _validate_versions(versions)
    _validate_digest(app_build_digest, "应用构建")
    parsed_base = urlparse(base_url)
    if (
        parsed_base.scheme != "https"
        or not parsed_base.hostname
        or parsed_base.username is not None
        or parsed_base.password is not None
        or parsed_base.path not in {"", "/"}
        or parsed_base.params
        or parsed_base.query
        or parsed_base.fragment
    ):
        raise EvaluationInputError("安全回归只允许访问显式 HTTPS 受控部署")
    if not isinstance(key_id, str) or not key_id.strip():
        raise EvaluationInputError("安全证据 key_id 不能为空")
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or not 1 <= ttl_seconds <= _MAX_ATTESTATION_LIFETIME_SECONDS
    ):
        raise EvaluationInputError("安全证据有效期必须在 1 到 3600 秒之间")

    eligible = {case.id: case for case in dataset.eligible_cases(normalized_split)}
    supplied_ids = [target.case_id for target in targets]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise EvaluationInputError("安全回归目标包含重复案例")
    missing = sorted(set(eligible) - set(supplied_ids))
    unknown = sorted(set(supplied_ids) - set(eligible))
    if missing:
        raise EvaluationInputError(f"缺少已准入案例安全目标：{len(missing)} 条")
    if unknown:
        raise EvaluationInputError(f"包含未知案例安全目标：{len(unknown)} 条")

    health = transport.get(
        _url(base_url, "/health"),
        headers=_request_headers(),
    )
    _assert_deployed_build(health, app_build_digest)
    if health.status_code != 200 or not isinstance(health.json_body, dict):
        raise EvaluationInputError("受控部署健康检查失败")
    deployment_environment = health.json_body.get("environment")
    if not isinstance(deployment_environment, str) or not deployment_environment:
        raise EvaluationInputError("受控部署未返回环境标识")

    dataset_digest = _dataset_digest(dataset, normalized_split)
    case_results: list[dict[str, Any]] = []
    for target in targets:
        if (
            isinstance(target.task_id, bool)
            or not isinstance(target.task_id, int)
            or target.task_id <= 0
            or isinstance(target.foreign_control_task_id, bool)
            or not isinstance(target.foreign_control_task_id, int)
            or target.foreign_control_task_id <= 0
            or target.foreign_control_task_id == target.task_id
            or not _ENV_NAME_PATTERN.fullmatch(target.owner_session_env)
            or not _ENV_NAME_PATTERN.fullmatch(target.foreign_session_env)
        ):
            raise EvaluationInputError("安全回归目标字段不合法")
        owner_session = _session_id(
            credentials.get(target.owner_session_env),
            env_name=target.owner_session_env,
        )
        foreign_session = _session_id(
            credentials.get(target.foreign_session_env),
            env_name=target.foreign_session_env,
        )
        if owner_session == foreign_session:
            raise EvaluationInputError("owner 与 foreign 必须是不同的有效会话")

        resource_url = _url(
            base_url,
            f"/api/design/tasks/{target.task_id}/generation",
        )
        foreign_control = transport.get(
            _url(
                base_url,
                "/api/design/tasks/"
                f"{target.foreign_control_task_id}/generation",
            ),
            headers=_request_headers(foreign_session),
        )
        owner = transport.get(
            resource_url,
            headers=_request_headers(owner_session),
        )
        foreign = transport.get(
            resource_url,
            headers=_request_headers(foreign_session),
        )
        _assert_deployed_build(foreign_control, app_build_digest)
        _assert_deployed_build(owner, app_build_digest)
        _assert_deployed_build(foreign, app_build_digest)
        if (
            foreign_control.status_code != 200
            or not isinstance(foreign_control.json_body, dict)
            or isinstance(foreign_control.json_body.get("run_id"), bool)
            or not isinstance(foreign_control.json_body.get("run_id"), int)
            or foreign_control.json_body["run_id"] <= 0
        ):
            raise EvaluationInputError(
                "foreign 会话无法读取自身控制资源，身份检查失败"
            )
        if owner.status_code != 200 or not isinstance(owner.json_body, dict):
            raise EvaluationInputError("owner 无法读取绑定的真实生成运行")
        run_id = owner.json_body.get("run_id")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise EvaluationInputError("owner 响应缺少真实生成运行标识")
        if foreign.status_code != 404 and not 200 <= foreign.status_code < 300:
            raise EvaluationInputError("foreign 访问结果不确定，拒绝签发安全证据")

        case_digest = _case_fingerprint(dataset_digest, target.case_id)
        severe_count = 1 if 200 <= foreign.status_code < 300 else 0
        case_results.append(
            {
                "case_fingerprint": case_digest,
                "resource_binding_digest": _resource_binding_digest(
                    dataset_digest=dataset_digest,
                    case_digest=case_digest,
                    task_id=target.task_id,
                    run_id=run_id,
                    binding_key=signing_key,
                ),
                "check_count": 1,
                "severe_count": severe_count,
                "owner_status": owner.status_code,
                "foreign_status": foreign.status_code,
            }
        )

    issued_at = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        raise EvaluationInputError("安全证据签发时间必须包含时区")
    issued_at = issued_at.astimezone(timezone.utc)
    unsigned: dict[str, Any] = {
        "schema_version": SECURITY_EVIDENCE_SCHEMA_VERSION,
        "evidence_type": SECURITY_EVIDENCE_TYPE,
        "suite_version": SECURITY_SUITE_VERSION,
        "issued_at": issued_at.isoformat(),
        "expires_at": (issued_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "app_build_digest": app_build_digest,
        "deployment_environment": deployment_environment,
        "dataset_fingerprint": dataset_digest,
        "split": normalized_split,
        "versions": asdict(versions),
        "check_count": len(case_results),
        "severe_count": sum(item["severe_count"] for item in case_results),
        "cases": sorted(case_results, key=lambda item: item["case_fingerprint"]),
    }
    return {
        **unsigned,
        "attestation": {
            "algorithm": SECURITY_SIGNATURE_ALGORITHM,
            "key_id": key_id.strip(),
            "signature": _sign(unsigned, signing_key),
        },
    }


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationInputError(f"安全证据缺少 {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationInputError(f"安全证据 {label} 不合法") from exc
    if parsed.tzinfo is None:
        raise EvaluationInputError(f"安全证据 {label} 必须包含时区")
    return parsed.astimezone(timezone.utc)


def verify_security_access_attestation(
    *,
    payload: Mapping[str, Any],
    dataset: RealWorldDataset,
    split: EvaluationSplit,
    versions: EvaluationVersions,
    expected_app_build_digest: str,
    verification_keys: Mapping[str, str],
    evaluation_key_id: str,
    expected_run_bindings: Mapping[str, tuple[int, int]] | None = None,
    expected_resource_binding_digests: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> VerifiedSecurityAccessAttestation:
    """验签并用数据集、版本和真实 run 绑定重新派生安全计数。"""
    normalized_split = validate_evaluation_split(split)
    expected_fields = {
        "schema_version",
        "evidence_type",
        "suite_version",
        "issued_at",
        "expires_at",
        "app_build_digest",
        "deployment_environment",
        "dataset_fingerprint",
        "split",
        "versions",
        "check_count",
        "severe_count",
        "cases",
        "attestation",
    }
    if set(payload) != expected_fields:
        raise EvaluationInputError("独立安全证据字段不合法")
    if payload.get("schema_version") != SECURITY_EVIDENCE_SCHEMA_VERSION:
        raise EvaluationInputError("独立安全证据 schema_version 不受支持")
    if payload.get("evidence_type") != SECURITY_EVIDENCE_TYPE:
        raise EvaluationInputError("证据不是跨用户真实 HTTP 安全证据")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict) or set(attestation) != {
        "algorithm",
        "key_id",
        "signature",
    }:
        raise EvaluationInputError("独立安全证据签名字段不合法")
    key_id = attestation.get("key_id")
    if key_id == evaluation_key_id:
        raise EvaluationInputError("安全证据必须使用独立于评测证据的 key_id")
    if attestation.get("algorithm") != SECURITY_SIGNATURE_ALGORITHM:
        raise EvaluationInputError("独立安全证据签名算法不受支持")
    if not isinstance(key_id, str) or key_id not in verification_keys:
        raise EvaluationInputError("缺少独立安全证据验签密钥")
    supplied_signature = attestation.get("signature")
    unsigned = {key: value for key, value in payload.items() if key != "attestation"}
    expected_signature = _sign(unsigned, verification_keys[key_id])
    if not isinstance(supplied_signature, str) or not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        raise EvaluationInputError("独立安全证据签名无效")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise EvaluationInputError("安全证据验证时间必须包含时区")
    current = current.astimezone(timezone.utc)
    issued_at = _parse_time(payload.get("issued_at"), "issued_at")
    expires_at = _parse_time(payload.get("expires_at"), "expires_at")
    if issued_at > current + timedelta(seconds=_CLOCK_SKEW_SECONDS):
        raise EvaluationInputError("独立安全证据签发时间在未来")
    if expires_at <= current:
        raise EvaluationInputError("独立安全证据已过期，禁止重放")
    lifetime = (expires_at - issued_at).total_seconds()
    if not 0 < lifetime <= _MAX_ATTESTATION_LIFETIME_SECONDS:
        raise EvaluationInputError("独立安全证据有效期不合法")

    _validate_digest(expected_app_build_digest, "期望应用构建")
    if payload.get("app_build_digest") != expected_app_build_digest:
        raise EvaluationInputError("独立安全证据与当前应用构建不一致")
    if payload.get("split") != normalized_split:
        raise EvaluationInputError("独立安全证据 split 不一致")
    _validate_versions(versions)
    if payload.get("versions") != asdict(versions):
        raise EvaluationInputError("独立安全证据与当前评测版本不一致")
    dataset_digest = _dataset_digest(dataset, normalized_split)
    if payload.get("dataset_fingerprint") != dataset_digest:
        raise EvaluationInputError("独立安全证据与当前数据集不一致")
    if payload.get("suite_version") != SECURITY_SUITE_VERSION:
        raise EvaluationInputError("独立安全回归 suite_version 不受支持")
    environment = payload.get("deployment_environment")
    if not isinstance(environment, str) or not environment:
        raise EvaluationInputError("独立安全证据缺少部署环境")

    eligible = {case.id: case for case in dataset.eligible_cases(normalized_split)}
    if (expected_run_bindings is None) == (
        expected_resource_binding_digests is None
    ):
        raise EvaluationInputError("必须提供且只能提供一种安全运行绑定")
    if expected_run_bindings is not None:
        if set(expected_run_bindings) != set(eligible):
            raise EvaluationInputError("独立安全证据期望运行集合不完整")
        expected_by_fingerprint = {
            _case_fingerprint(dataset_digest, case_id): _resource_binding_digest(
                dataset_digest=dataset_digest,
                case_digest=_case_fingerprint(dataset_digest, case_id),
                task_id=task_id,
                run_id=run_id,
                binding_key=verification_keys[key_id],
            )
            for case_id, (task_id, run_id) in expected_run_bindings.items()
            if not any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in (task_id, run_id)
            )
        }
        if len(expected_by_fingerprint) != len(eligible):
            raise EvaluationInputError("独立安全证据期望运行绑定不合法")
    else:
        assert expected_resource_binding_digests is not None
        expected_by_fingerprint = dict(expected_resource_binding_digests)
        if set(expected_by_fingerprint) != {
            _case_fingerprint(dataset_digest, case_id) for case_id in eligible
        } or any(
            not isinstance(value, str)
            or not _RESOURCE_BINDING_PATTERN.fullmatch(value)
            for value in expected_by_fingerprint.values()
        ):
            raise EvaluationInputError("独立安全证据匿名运行绑定不完整")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationInputError("独立安全证据 cases 必须是数组")
    results: list[SecurityCaseResult] = []
    seen: set[str] = set()
    required_case_fields = {
        "case_fingerprint",
        "resource_binding_digest",
        "check_count",
        "severe_count",
        "owner_status",
        "foreign_status",
    }
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != required_case_fields:
            raise EvaluationInputError("独立安全案例字段不合法")
        case_digest = raw.get("case_fingerprint")
        if case_digest not in expected_by_fingerprint or case_digest in seen:
            raise EvaluationInputError("独立安全证据包含未知或重复案例")
        seen.add(case_digest)
        expected_binding_digest = expected_by_fingerprint[case_digest]
        if raw.get("resource_binding_digest") != expected_binding_digest:
            raise EvaluationInputError("独立安全证据运行绑定不一致，禁止重放")
        owner_status = raw.get("owner_status")
        foreign_status = raw.get("foreign_status")
        derived_severe = (
            1
            if isinstance(foreign_status, int)
            and not isinstance(foreign_status, bool)
            and 200 <= foreign_status < 300
            else 0
        )
        if (
            owner_status != 200
            or (foreign_status != 404 and derived_severe != 1)
            or raw.get("check_count") != 1
            or raw.get("severe_count") != derived_severe
        ):
            raise EvaluationInputError("独立安全计数与签名 HTTP 事实不一致")
        results.append(
            SecurityCaseResult(
                case_fingerprint=case_digest,
                resource_binding_digest=str(raw["resource_binding_digest"]),
                check_count=1,
                severe_count=derived_severe,
                owner_status=owner_status,
                foreign_status=foreign_status,
            )
        )
    missing = set(expected_by_fingerprint) - seen
    if missing:
        raise EvaluationInputError(f"缺少已准入案例安全证据：{len(missing)} 条")
    derived_check_count = sum(item.check_count for item in results)
    derived_severe_count = sum(item.severe_count for item in results)
    if (
        derived_check_count <= 0
        or payload.get("check_count") != derived_check_count
        or payload.get("severe_count") != derived_severe_count
    ):
        raise EvaluationInputError("独立安全汇总与签名 HTTP 事实不一致")

    return VerifiedSecurityAccessAttestation(
        suite_version=SECURITY_SUITE_VERSION,
        app_build_digest=expected_app_build_digest,
        deployment_environment=environment,
        dataset_fingerprint=dataset_digest,
        split=normalized_split,
        versions=versions,
        issued_at=issued_at,
        expires_at=expires_at,
        case_results=tuple(results),
        check_count=derived_check_count,
        severe_count=derived_severe_count,
        key_id=key_id,
        evidence_digest=_digest(payload),
    )
