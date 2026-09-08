"""核验受控生产 cohort 的商品与报价来源可追溯性。"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from app.db.database import SessionLocal
from app.services.plan_traceability_audit_service import (
    PlanTraceabilityCohortError,
    audit_plan_traceability,
    load_plan_traceability_cohort,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验生产 cohort 的方案与报价来源")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--cohort-manifest", type=Path, required=True)
    parser.add_argument("--environment", required=True, help="受控执行环境标识")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        key_id = os.getenv("PLAN_TRACEABILITY_COHORT_KEY_ID", "").strip()
        signing_key = os.getenv("PLAN_TRACEABILITY_COHORT_HMAC_KEY", "")
        if not key_id or not signing_key:
            raise PlanTraceabilityCohortError("缺少 cohort 验签环境变量")
        cohort = load_plan_traceability_cohort(
            args.cohort_manifest,
            expected_environment=args.environment,
            verification_keys={key_id: signing_key},
        )
        with SessionLocal() as db:
            report = audit_plan_traceability(
                db,
                cohort=cohort,
                sample_size=args.sample_size,
            )
        payload = asdict(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"TRACEABILITY_AUDIT_ERROR={exc}")
        return 2

    status = "PASS" if report.passed else "FAIL"
    print(f"TRACEABILITY_AUDIT={status}")
    print(f"AUDITED={report.audited_plan_count}")
    print(f"MINIMUM_REQUIRED={report.minimum_required}")
    print(f"COHORT={report.cohort_id}")
    print(f"CUTOVER={report.cutover_id}")
    print(f"ENVIRONMENT={report.environment}")
    print(f"REPORT_JSON={args.output.resolve()}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
