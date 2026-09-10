"""真实案例评测的数据源选择与受保护治理库访问边界。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.database import SessionLocal
from app.services.real_world_governance_service import (
    RealWorldGovernanceError,
    load_frozen_dataset_for_evaluation,
)
from evals.real_world import (
    EvaluationInputError,
    RealWorldDataset,
    load_case_manifest,
)


def add_dataset_source_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--dataset-version")
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--review-root", type=Path)


def _require_protected_governance_access() -> None:
    if (
        os.getenv("REAL_WORLD_PROTECTED_EVAL", "").strip() != "1"
        or os.getenv("GITHUB_EVENT_NAME", "") != "workflow_dispatch"
        or os.getenv("REAL_WORLD_RUNNER_ENVIRONMENT", "") != "self-hosted"
    ):
        raise EvaluationInputError(
            "治理冻结数据仅允许受保护的 self-hosted 手工工作流读取"
        )


def load_dataset_source(
    *,
    manifest: Path | None,
    dataset_version: str | None,
    asset_root: Path | None,
    review_root: Path | None,
) -> tuple[RealWorldDataset, Path]:
    """加载唯一显式数据源，并返回人工评审文件的受控根目录。"""
    if (manifest is None) == (dataset_version is None):
        raise EvaluationInputError("必须且只能选择 manifest 或 dataset-version")
    if manifest is not None:
        dataset = load_case_manifest(manifest, asset_root=asset_root)
        default_root = (
            asset_root.resolve() if asset_root is not None else manifest.resolve().parent
        )
        resolved_review_root = review_root.resolve() if review_root else default_root
        if not resolved_review_root.is_dir():
            raise EvaluationInputError("review-root 不存在或不是目录")
        return dataset, resolved_review_root
    if asset_root is not None:
        raise EvaluationInputError("dataset-version 模式不得指定 asset-root")

    normalized_version = str(dataset_version or "").strip()
    if not normalized_version:
        raise EvaluationInputError("dataset-version 不能为空")
    _require_protected_governance_access()
    if review_root is None:
        raise EvaluationInputError("dataset-version 模式必须显式提供 review-root")
    resolved_review_root = review_root.resolve()
    if not resolved_review_root.is_dir():
        raise EvaluationInputError("review-root 不存在或不是目录")
    upload_root = Path(settings.upload_dir).resolve()
    try:
        with SessionLocal() as db:
            dataset = load_frozen_dataset_for_evaluation(
                db,
                normalized_version,
                upload_root=upload_root,
            )
    except RealWorldGovernanceError as exc:
        raise EvaluationInputError(f"冻结数据集不可用：{exc}") from exc
    except SQLAlchemyError as exc:
        raise EvaluationInputError("冻结数据集数据库读取失败") from exc
    return dataset, resolved_review_root


def source_arguments(namespace: Any) -> dict[str, Any]:
    return {
        "manifest": getattr(namespace, "manifest", None),
        "dataset_version": getattr(namespace, "dataset_version", None),
        "asset_root": getattr(namespace, "asset_root", None),
        "review_root": getattr(namespace, "review_root", None),
    }
