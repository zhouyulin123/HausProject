import json
from pathlib import Path

import pytest

from evals.agent_action_plan import run_synthetic_development_eval
from evals.cases.agent_action_plan import synthetic_development_cases
from evals.run_agent_action_plan_eval import main


pytestmark = pytest.mark.unit


def _fixture_planner(cases):
    plans = {case["instruction"]: case["fixture_plan"] for case in cases}

    def planner(*, instruction, context):
        assert context
        return plans[instruction]

    return planner


def test_action_plan_eval_covers_contract_without_exposing_prompt_content():
    cases = synthetic_development_cases()
    report = run_synthetic_development_eval(
        cases,
        planner=_fixture_planner(cases),
        execution_mode="deterministic_fixture",
    )

    assert report["schema_version"] == "agent-action-plan-eval/1.0"
    assert report["dataset_kind"] == "synthetic_development"
    assert report["claim"] == "engineering_contract_only"
    assert report["execution_mode"] == "deterministic_fixture"
    assert report["versions"]["schema"] == "agent-action-plan/1.0"
    assert report["versions"]["prompt_version"] == "agent-action-planner/1.0"
    assert report["versions"]["prompt_digest"].startswith("sha256:")
    assert (
        report["versions"]["context_policy_version"]
        == "agent-action-context-policy/1.0"
    )
    assert report["versions"]["dataset_digest"].startswith("sha256:")
    assert report["overall_passed"] is True
    assert report["metrics"]["case_count"] == 5
    assert report["metrics"]["passed_case_count"] == 5
    assert report["metrics"]["valid_output_rate"] == 1.0
    assert report["metrics"]["reference_integrity_rate"] == 1.0
    assert report["metrics"]["planner_call_count"] == 5
    assert {row["case_id"] for row in report["cases"]} == {
        "create-and-place",
        "edit-current",
        "move-near-opening",
        "ambiguous-target",
        "unsupported-tool",
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert all(case["instruction"] not in serialized for case in cases)
    assert "chair-private-label" not in serialized


@pytest.mark.parametrize(
    ("fixture_plan", "expected_error"),
    [
        (
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "移动家具",
                "steps": [
                    {
                        "id": "move",
                        "tool": "scene.move_item",
                        "instanceId": "invented-chair",
                        "placement": {"kind": "room_center"},
                    }
                ],
            },
            "unknown_instance_reference",
        ),
        (
            {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "移动家具",
                "steps": [
                    {
                        "id": "move",
                        "tool": "scene.move_item",
                        "instanceId": "chair-a",
                        "placement": {
                            "kind": "near_opening",
                            "openingId": "invented-window",
                        },
                    }
                ],
            },
            "unknown_opening_reference",
        ),
    ],
)
def test_action_plan_eval_rejects_invented_context_references(
    fixture_plan,
    expected_error,
):
    case = synthetic_development_cases()[2]
    case = {**case, "fixture_plan": fixture_plan}
    report = run_synthetic_development_eval(
        [case],
        planner=_fixture_planner([case]),
        execution_mode="deterministic_fixture",
    )

    assert report["overall_passed"] is False
    assert expected_error in report["cases"][0]["error_codes"]
    assert report["metrics"]["reference_integrity_rate"] == 0.0


def test_action_plan_eval_fails_closed_on_context_mutation_and_planner_exception():
    cases = synthetic_development_cases()[:2]

    def planner(*, instruction, context):
        if instruction == cases[0]["instruction"]:
            context["scene"]["id"] = 999
            return cases[0]["fixture_plan"]
        raise RuntimeError("do not expose this provider detail")

    report = run_synthetic_development_eval(
        cases,
        planner=planner,
        execution_mode="online_llm",
    )

    assert report["overall_passed"] is False
    assert report["cases"][0]["error_codes"] == ["context_mutated"]
    assert report["cases"][1]["error_codes"] == ["planner_failed"]
    assert "provider detail" not in json.dumps(report)


def test_action_plan_eval_cli_writes_offline_report(tmp_path, capsys):
    output = tmp_path / "action-plan.json"

    exit_code = main(["--output", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["overall_passed"] is True
    assert payload["execution_mode"] == "deterministic_fixture"
    assert "ACTION_PLAN_EVAL_PASSED=true" in capsys.readouterr().out


def test_quality_workflow_runs_action_plan_contract_eval():
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "python -m evals.run_agent_action_plan_eval" in workflow
