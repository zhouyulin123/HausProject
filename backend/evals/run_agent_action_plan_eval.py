"""运行统一动作规划合成开发评测。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from app.core.config import settings
from app.services import llm_service
from evals.agent_action_plan import run_synthetic_development_eval
from evals.cases.agent_action_plan import synthetic_development_cases


def _fixture_planner(cases: list[dict[str, object]]):
    plans = {
        str(case["instruction"]): deepcopy(case["fixture_plan"])
        for case in cases
    }

    def planner(*, instruction: str, context: dict):
        del context
        return deepcopy(plans[instruction])

    return planner


def _attach_online_usage(report: dict, capture) -> None:
    usage = capture.usage
    metrics = report["metrics"]
    metrics["prompt_tokens"] = usage.get("prompt_tokens")
    metrics["completion_tokens"] = usage.get("completion_tokens")
    metrics["total_tokens"] = usage.get("total_tokens")
    cost = llm_service.estimate_cost_cny(
        usage,
        settings.llm_input_price_per_mtok,
        settings.llm_output_price_per_mtok,
    )
    metrics["llm_cost_cny"] = cost
    metrics["llm_cost_status"] = "known" if cost is not None else "unknown"
    report["model"] = settings.llm_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行统一动作规划工程契约评测")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".test_artifacts/agent_action_plan_eval.json"),
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="显式调用当前配置的真实文本模型；默认使用确定性夹具",
    )
    args = parser.parse_args(argv)
    cases = synthetic_development_cases()
    if args.online:
        with llm_service.capture_model_call() as capture:
            report = run_synthetic_development_eval(
                cases,
                planner=llm_service.plan_agent_actions,
                execution_mode="online_llm",
            )
        _attach_online_usage(report, capture)
    else:
        report = run_synthetic_development_eval(
            cases,
            planner=_fixture_planner(cases),
            execution_mode="deterministic_fixture",
        )

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"ACTION_PLAN_EVAL_PASSED={str(report['overall_passed']).lower()}")
    print(f"ACTION_PLAN_EVAL_REPORT={output}")
    return 0 if report["overall_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
