"""随机抽检完成方案的商品与报价来源可追溯性。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.db.database import SessionLocal
from app.services.plan_traceability_audit_service import audit_plan_traceability


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抽检不可变方案与报价来源")
    parser.add_argument("--seed", required=True, help="审计批次种子，例如 2026-W36")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        with SessionLocal() as db:
            report = audit_plan_traceability(
                db,
                sample_size=args.sample_size,
                seed=args.seed,
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
    print(f"SAMPLED={report.sampled_plan_count}/{report.requested_sample_size}")
    print(f"REPORT_JSON={args.output.resolve()}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
