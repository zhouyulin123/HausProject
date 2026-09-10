from __future__ import annotations

import json

from evals.cases.open_geometry import synthetic_development_case
from evals.open_geometry import run_synthetic_development_eval
from evals.run_open_geometry_eval import main


def test_synthetic_open_geometry_track_covers_multiturn_repair_and_unsupported():
    report = run_synthetic_development_eval(synthetic_development_case())

    assert report["dataset_kind"] == "synthetic_development"
    assert report["claim"] == "engineering_contract_only"
    assert report["overall_passed"] is True
    assert report["metrics"]["turn_count"] == 6
    assert report["metrics"]["turn_pass_rate"] == 1.0
    assert report["metrics"]["planner_call_count"] == 7
    assert report["metrics"]["structured_repair_count"] == 1
    assert report["metrics"]["unsupported_preservation_count"] == 1
    assert report["metrics"]["llm_cost_cny"] is None
    assert report["metrics"]["llm_cost_status"] == "not_measured_offline"


def test_open_geometry_eval_runner_writes_report(tmp_path):
    output = tmp_path / "open-geometry.json"

    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overall_passed"] is True
