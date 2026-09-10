"""运行开放几何合成开发评测并输出机器可读报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.cases.open_geometry import synthetic_development_case
from evals.open_geometry import run_synthetic_development_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行开放几何工程契约评测")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".test_artifacts/open_geometry_eval.json"),
    )
    args = parser.parse_args(argv)
    report = run_synthetic_development_eval(synthetic_development_case())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OPEN_GEOMETRY_EVAL_PASSED={str(report['overall_passed']).lower()}")
    print(f"OPEN_GEOMETRY_EVAL_REPORT={output}")
    return 0 if report["overall_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
