"""对不可变方案快照执行可复现的商品与报价来源抽检。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DesignPlanVersion
from app.services.design_version_service import recalculate_quote_snapshot


_MAX_COHORT_BYTES = 1024 * 1024
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PlanTraceabilityCohortError(ValueError):
    """生产验收 cohort 缺失、未受信或与执行环境不一致。"""


@dataclass(frozen=True)
class PlanTraceabilityCohortMember:
    task_id: int
    plan_version_id: int


@dataclass(frozen=True)
class PlanTraceabilityCohort:
    cohort_id: str
    cutover_id: str
    environment: str
    issued_at: str
    members: tuple[PlanTraceabilityCohortMember, ...]
    manifest_digest: str
    signature_key_id: str


@dataclass(frozen=True)
class PlanTraceabilityBindingResult:
    plan_version_id: int
    task_id: int
    passed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PlanTraceabilityResult:
    plan_version_id: int
    task_id: int
    revision_version: int
    plan_key: str
    passed: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PlanTraceabilityAuditReport:
    schema_version: str
    cohort_id: str
    cutover_id: str
    environment: str
    manifest_digest: str
    signature_key_id: str
    minimum_required: int
    eligible_member_count: int
    audited_plan_count: int
    minimum_shortfall: int
    passed: bool
    bindings: tuple[PlanTraceabilityBindingResult, ...]
    results: tuple[PlanTraceabilityResult, ...]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PlanTraceabilityCohortError(f"{label}字段不完整或包含未知字段")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise PlanTraceabilityCohortError(f"{label}格式无效")
    return value


def load_plan_traceability_cohort(
    path: Path | str,
    *,
    expected_environment: str,
    verification_keys: dict[str, str],
) -> PlanTraceabilityCohort:
    """加载受控签名 cohort；不根据历史字段、日期或生成器推断成员。"""
    manifest_path = Path(path)
    try:
        if not manifest_path.is_file() or manifest_path.stat().st_size > _MAX_COHORT_BYTES:
            raise PlanTraceabilityCohortError("cohort manifest 不存在或过大")
        raw = manifest_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except PlanTraceabilityCohortError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanTraceabilityCohortError("cohort manifest 无法读取或不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise PlanTraceabilityCohortError("cohort manifest 必须是对象")
    _exact_keys(
        payload,
        {
            "schema_version", "cohort_kind", "cohort_id", "cutover_id",
            "environment", "issued_at", "members", "attestation",
        },
        "cohort manifest",
    )
    if payload["schema_version"] != "1.0":
        raise PlanTraceabilityCohortError("只接受 cohort manifest 1.0")
    if payload["cohort_kind"] != "production_acceptance":
        raise PlanTraceabilityCohortError("cohort_kind 必须是 production_acceptance")
    cohort_id = _identifier(payload["cohort_id"], "cohort_id")
    cutover_id = _identifier(payload["cutover_id"], "cutover_id")
    environment = _identifier(payload["environment"], "environment")
    expected = _identifier(expected_environment, "预期环境")
    if environment != expected:
        raise PlanTraceabilityCohortError("cohort 环境与当前审计环境不匹配")
    if not isinstance(payload["issued_at"], str):
        raise PlanTraceabilityCohortError("issued_at 格式无效")
    try:
        issued_at = datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanTraceabilityCohortError("issued_at 格式无效") from exc
    if issued_at.tzinfo is None:
        raise PlanTraceabilityCohortError("issued_at 必须包含时区")

    raw_members = payload["members"]
    if not isinstance(raw_members, list) or not 1 <= len(raw_members) <= 10_000:
        raise PlanTraceabilityCohortError("members 必须包含 1 到 10000 个成员")
    members: list[PlanTraceabilityCohortMember] = []
    identities: set[tuple[int, int]] = set()
    plan_ids: set[int] = set()
    for raw_member in raw_members:
        if not isinstance(raw_member, dict):
            raise PlanTraceabilityCohortError("cohort 成员必须是对象")
        _exact_keys(raw_member, {"task_id", "plan_version_id"}, "cohort 成员")
        task_id = raw_member["task_id"]
        plan_version_id = raw_member["plan_version_id"]
        if (
            not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1
            or not isinstance(plan_version_id, int)
            or isinstance(plan_version_id, bool)
            or plan_version_id < 1
        ):
            raise PlanTraceabilityCohortError("cohort 成员 ID 必须是正整数")
        identity = (task_id, plan_version_id)
        if identity in identities or plan_version_id in plan_ids:
            raise PlanTraceabilityCohortError("cohort 成员重复或方案绑定冲突")
        identities.add(identity)
        plan_ids.add(plan_version_id)
        members.append(PlanTraceabilityCohortMember(task_id, plan_version_id))

    attestation = payload["attestation"]
    if not isinstance(attestation, dict):
        raise PlanTraceabilityCohortError("cohort 缺少签名证明")
    _exact_keys(attestation, {"algorithm", "key_id", "signature"}, "签名证明")
    if attestation["algorithm"] != "hmac-sha256":
        raise PlanTraceabilityCohortError("cohort 签名算法不受支持")
    key_id = _identifier(attestation["key_id"], "签名 key_id")
    signing_key = verification_keys.get(key_id)
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise PlanTraceabilityCohortError("缺少可信 cohort 验签密钥")
    signature = attestation["signature"]
    if not isinstance(signature, str) or not _SIGNATURE_PATTERN.fullmatch(signature):
        raise PlanTraceabilityCohortError("cohort 签名格式无效")
    unsigned = {key: value for key, value in payload.items() if key != "attestation"}
    expected_signature = hmac.new(
        signing_key.encode("utf-8"), _canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise PlanTraceabilityCohortError("cohort 签名验证失败")
    return PlanTraceabilityCohort(
        cohort_id=cohort_id,
        cutover_id=cutover_id,
        environment=environment,
        issued_at=payload["issued_at"],
        members=tuple(members),
        manifest_digest=f"sha256:{hashlib.sha256(_canonical_json(payload)).hexdigest()}",
        signature_key_id=key_id,
    )


def _nonlegacy_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().lower() != "legacy"
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _money(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _quantity(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def _line_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("sku"),
        item.get("quantity"),
        item.get("unitPrice"),
        item.get("subtotal"),
        item.get("dataVersion"),
        item.get("recordVersion"),
    )


def _audit_plan(plan: DesignPlanVersion) -> PlanTraceabilityResult:
    reasons: list[str] = []
    snapshot = plan.quote_snapshot
    if snapshot is None:
        return PlanTraceabilityResult(
            plan_version_id=plan.id,
            task_id=plan.revision.task_id,
            revision_version=plan.revision.version,
            plan_key=plan.plan_key,
            passed=False,
            reason_codes=("quote_snapshot_missing",),
        )

    for field_name, value in (
        ("catalog_version", snapshot.catalog_version),
        ("price_version", snapshot.price_version),
        ("rule_version", snapshot.rule_version),
    ):
        if not _nonlegacy_text(value):
            reasons.append(f"{field_name}_missing")

    quote = snapshot.quote_json
    if not isinstance(quote, dict):
        reasons.append("quote_payload_invalid")
        quote = {}
    plan_payload = plan.plan_json if isinstance(plan.plan_json, dict) else {}
    if plan_payload.get("shopQuote") != quote:
        reasons.append("quote_payload_mismatch")

    line_items = quote.get("lineItems")
    if not isinstance(line_items, list):
        reasons.append("quote_line_items_invalid")
        line_items = []
    valid_lines: list[dict[str, Any]] = []
    line_subtotal_mismatch = False
    for raw_line in line_items:
        if not isinstance(raw_line, dict):
            reasons.append("quote_line_invalid")
            continue
        valid_lines.append(raw_line)
        if not _nonlegacy_text(raw_line.get("sku")):
            reasons.append("quote_line_sku_missing")
        if not _quantity(raw_line.get("quantity")):
            reasons.append("quote_line_quantity_invalid")
        if not _money(raw_line.get("unitPrice")):
            reasons.append("quote_line_price_invalid")
        if not _money(raw_line.get("subtotal")):
            reasons.append("quote_line_subtotal_invalid")
        elif _quantity(raw_line.get("quantity")) and _money(
            raw_line.get("unitPrice")
        ):
            expected = round(raw_line["unitPrice"] * raw_line["quantity"])
            if raw_line["subtotal"] != expected:
                line_subtotal_mismatch = True
                reasons.append("quote_line_subtotal_mismatch")
        if not _nonlegacy_text(raw_line.get("dataVersion")):
            reasons.append("quote_line_data_version_missing")
        if not _positive_int(raw_line.get("recordVersion")):
            reasons.append("quote_line_record_version_invalid")

    expected_versions = [
        {
            "sku": item.get("sku"),
            "dataVersion": item.get("dataVersion"),
            "recordVersion": item.get("recordVersion"),
        }
        for item in valid_lines
        if item.get("sku")
    ]
    if snapshot.sku_versions_json != expected_versions:
        reasons.append("sku_version_snapshot_mismatch")

    custom_lines = quote.get("customLineItems")
    if not isinstance(custom_lines, list):
        reasons.append("custom_quote_lines_invalid")
        custom_lines = []
    for raw_line in custom_lines:
        if not isinstance(raw_line, dict):
            reasons.append("custom_quote_line_invalid")
            continue
        if not _positive_int(raw_line.get("ruleId")):
            reasons.append("custom_rule_id_missing")
        if not _nonlegacy_text(raw_line.get("dataVersion")):
            reasons.append("custom_rule_data_version_missing")
        if not _positive_int(raw_line.get("recordVersion")):
            reasons.append("custom_rule_record_version_invalid")

    products = plan_payload.get("furnitureSuggestions")
    if not isinstance(products, list):
        reasons.append("product_snapshot_invalid")
        products = []
    product_lines: list[dict[str, Any]] = []
    for raw_product in products:
        if not isinstance(raw_product, dict):
            reasons.append("product_snapshot_item_invalid")
            continue
        product_lines.append(raw_product)
        if raw_product.get("dataStatus") != "verified":
            reasons.append("product_not_verified")
        if not _nonlegacy_text(raw_product.get("sourceName")):
            reasons.append("product_source_missing")
        if not _nonlegacy_text(raw_product.get("verifiedAt")):
            reasons.append("product_verification_time_missing")
        if not _nonlegacy_text(raw_product.get("dataVersion")):
            reasons.append("product_data_version_missing")
        if not _positive_int(raw_product.get("recordVersion")):
            reasons.append("product_record_version_invalid")

    if sorted(_line_identity(item) for item in valid_lines) != sorted(
        _line_identity(item) for item in product_lines
    ):
        reasons.append("product_quote_line_mismatch")

    recalculated = recalculate_quote_snapshot(snapshot)
    if line_subtotal_mismatch or not recalculated["consistent"]:
        reasons.append("quote_snapshot_inconsistent")

    normalized_reasons = tuple(dict.fromkeys(reasons))
    return PlanTraceabilityResult(
        plan_version_id=plan.id,
        task_id=plan.revision.task_id,
        revision_version=plan.revision.version,
        plan_key=plan.plan_key,
        passed=not normalized_reasons,
        reason_codes=normalized_reasons,
    )


def audit_plan_traceability(
    db: Session,
    *,
    cohort: PlanTraceabilityCohort | None,
    sample_size: int = 20,
) -> PlanTraceabilityAuditReport:
    """核验签名 cohort 的全部成员；sample_size 只是最低数量门槛。"""
    if not 1 <= sample_size <= 100:
        raise ValueError("sample_size 必须在 1 到 100 之间")
    if cohort is None:
        raise PlanTraceabilityCohortError("必须提供已验签的生产验收 cohort")

    plan_ids = [member.plan_version_id for member in cohort.members]
    found = list(
        db.scalars(
            select(DesignPlanVersion)
            .options(
                selectinload(DesignPlanVersion.quote_snapshot),
                selectinload(DesignPlanVersion.revision),
            )
            .where(DesignPlanVersion.id.in_(plan_ids))
            .order_by(DesignPlanVersion.id)
            .execution_options(populate_existing=True)
        ).unique()
    )
    by_id = {plan.id: plan for plan in found}
    bindings: list[PlanTraceabilityBindingResult] = []
    candidates: list[DesignPlanVersion] = []
    for member in cohort.members:
        plan = by_id.get(member.plan_version_id)
        reasons: list[str] = []
        if plan is None:
            reasons.append("plan_version_missing")
        else:
            if plan.revision.task_id != member.task_id:
                reasons.append("task_binding_mismatch")
            if plan.revision.status != "completed":
                reasons.append("revision_not_completed")
        bindings.append(PlanTraceabilityBindingResult(
            plan_version_id=member.plan_version_id,
            task_id=member.task_id,
            passed=not reasons,
            reason_codes=tuple(reasons),
        ))
        if not reasons and plan is not None:
            candidates.append(plan)
    sampled = sorted(candidates, key=lambda plan: plan.id)
    results = tuple(_audit_plan(plan) for plan in sampled)
    shortfall = max(0, sample_size - len(sampled))
    return PlanTraceabilityAuditReport(
        schema_version="2.0",
        cohort_id=cohort.cohort_id,
        cutover_id=cohort.cutover_id,
        environment=cohort.environment,
        manifest_digest=cohort.manifest_digest,
        signature_key_id=cohort.signature_key_id,
        minimum_required=sample_size,
        eligible_member_count=len(candidates),
        audited_plan_count=len(sampled),
        minimum_shortfall=shortfall,
        passed=(
            shortfall == 0
            and all(binding.passed for binding in bindings)
            and all(result.passed for result in results)
        ),
        bindings=tuple(bindings),
        results=results,
    )
