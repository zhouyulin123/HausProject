"""从数据库中的已完成系统运行签发真实案例评测证据。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.db.database import SessionLocal
from app.db.models import GenerationRun
from evals.real_world import EvaluationInputError, EvaluationVersions, load_case_manifest
from evals.trusted_evidence import RunBinding, collect_trusted_evidence


def _read_bindings(path: Path) -> tuple[RunBinding, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"无法读取运行绑定：{exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise EvaluationInputError("运行绑定 schema_version 必须为 1.0")
    if set(payload) != {"schema_version", "bindings"}:
        raise EvaluationInputError("运行绑定包含未知字段")
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list):
        raise EvaluationInputError("bindings 必须是数组")
    bindings: list[RunBinding] = []
    for index, raw in enumerate(raw_bindings):
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "task_id",
            "system_run_id",
        }:
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定字段不合法")
        case_id = raw.get("case_id")
        task_id = raw.get("task_id")
        run_id = raw.get("system_run_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定缺少 case_id")
        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id <= 0
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id <= 0
        ):
            raise EvaluationInputError(f"第 {index + 1} 条运行绑定 ID 不合法")
        bindings.append(RunBinding(case_id.strip(), task_id, run_id))
    return tuple(bindings)


def _model_version(db, bindings: tuple[RunBinding, ...]) -> str:
    models: set[str] = set()
    for binding in bindings:
        run = db.get(GenerationRun, binding.system_run_id)
        if run is None:
            raise EvaluationInputError(f"系统运行不存在：{binding.system_run_id}")
        if isinstance(run.model, str) and run.model.strip():
            models.add(run.model.strip())
    if len(models) != 1:
        raise EvaluationInputError("证据包内系统运行必须使用同一非空模型版本")
    return next(iter(models))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="签发真实系统执行评测证据")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--run-bindings", type=Path, required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--rules-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        signing_key = os.getenv("EVAL_EVIDENCE_HMAC_KEY", "")
        key_id = os.getenv("EVAL_EVIDENCE_KEY_ID", "")
        if not signing_key or not key_id:
            raise EvaluationInputError(
                "缺少签名密钥：必须配置 EVAL_EVIDENCE_HMAC_KEY 和 EVAL_EVIDENCE_KEY_ID"
            )
        dataset = load_case_manifest(args.manifest, asset_root=args.asset_root)
        bindings = _read_bindings(args.run_bindings.resolve())
        with SessionLocal() as db:
            versions = EvaluationVersions(
                model=_model_version(db, bindings),
                prompt=args.prompt_version,
                rules=args.rules_version,
                data=dataset.dataset_version,
            )
            bundle = collect_trusted_evidence(
                db,
                dataset=dataset,
                bindings=bindings,
                versions=versions,
                signing_key=signing_key,
                key_id=key_id,
            )
    except (EvaluationInputError, ValueError) as exc:
        print(f"EVAL_EVIDENCE_ERROR: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"EVIDENCE_JSON={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
