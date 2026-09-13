"""正式治理库及离线参考清单的匿名就绪度聚合。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RealWorldDatasetRevision
from app.services.real_world_governance_service import list_case_records
from evals.real_world import (
    DatasetValidationError,
    RealWorldDataset,
    load_case_manifest,
)


MINIMUM_REQUIRED = 20
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "cases"
    / "real_world"
    / "manifest.json"
)
DEFAULT_ASSET_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_SPLITS = ("development", "regression", "blind")


class RealWorldReadinessError(RuntimeError):
    """真实案例清单不可用，调用方必须失败关闭。"""


def build_governance_readiness(
    db: Session, *, checked_at: datetime | None = None
) -> dict:
    """正式治理库的匿名候选聚合；达到候选门槛不代表评测或发布通过。"""
    current = checked_at or datetime.now(timezone.utc)
    cases = list_case_records(db, now=current)
    eligible = [case for case in cases if not case.blockers]
    split_counts = {
        split: {
            "total": sum(case.split == split for case in cases),
            "eligible": sum(case.split == split for case in eligible),
        }
        for split in REQUIRED_SPLITS
    }
    frozen_count = (
        db.scalar(select(func.count()).select_from(RealWorldDatasetRevision)) or 0
    )
    latest = db.execute(
        select(
            RealWorldDatasetRevision.schema_version,
            RealWorldDatasetRevision.dataset_version,
        )
        .order_by(RealWorldDatasetRevision.id.desc())
        .limit(1)
    ).first()
    return {
        "source": "governance_database",
        "manifest_version": latest.schema_version if latest else None,
        "dataset_id": latest.dataset_version if latest else None,
        "frozen_dataset_count": frozen_count,
        "total": len(cases),
        "eligible_total": len(eligible),
        "private_real_eligible_total": len(eligible),
        "blocked_total": len(cases) - len(eligible),
        "split_counts": split_counts,
        "consent_status_counts": dict(
            sorted(Counter(case.consent_status for case in cases).items())
        ),
        "annotation_status_counts": dict(
            sorted(Counter(case.annotation_status for case in cases).items())
        ),
        "blocker_counts": dict(
            sorted(
                Counter(reason for case in cases for reason in case.blockers).items()
            )
        ),
        "minimum_required": MINIMUM_REQUIRED,
        "minimum_met": len(eligible) >= MINIMUM_REQUIRED
        and all(counts["eligible"] > 0 for counts in split_counts.values()),
        "checked_at": current,
    }


def _count_split(dataset: RealWorldDataset, split: str) -> dict[str, int]:
    cases = [case for case in dataset.cases if case.split == split]
    return {
        "total": len(cases),
        "eligible": sum(
            case.origin == "private_real" for case in dataset.eligible_cases(split)
        ),
    }


def build_real_world_readiness(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    asset_root: Path | str | None = None,
    checked_at: datetime | None = None,
) -> dict:
    """离线参考清单聚合；正式管理接口必须使用 build_governance_readiness。"""
    try:
        resolved_manifest = Path(manifest_path).resolve()
        resolved_asset_root = asset_root
        if (
            resolved_asset_root is None
            and resolved_manifest == DEFAULT_MANIFEST_PATH.resolve()
        ):
            resolved_asset_root = DEFAULT_ASSET_ROOT
        dataset = load_case_manifest(resolved_manifest, asset_root=resolved_asset_root)
    except (DatasetValidationError, OSError, ValueError) as exc:
        raise RealWorldReadinessError("真实案例清单不可用") from exc

    consent_counts = Counter(case.consent_status for case in dataset.cases)
    annotation_counts = Counter(case.annotation_status for case in dataset.cases)
    blocker_counts = Counter(
        reason for case in dataset.cases for reason in case.ineligible_reasons()
    )
    synthetic_release_cases = sum(
        case.origin == "synthetic" and case.split in REQUIRED_SPLITS
        for case in dataset.cases
    )
    if dataset.schema_version != "2.0":
        blocker_counts["trusted_schema_required"] = 1
    if synthetic_release_cases:
        blocker_counts["synthetic_release_case"] = synthetic_release_cases
    eligible_total = len(dataset.eligible_cases())
    private_real_eligible_total = sum(
        case.origin == "private_real" for case in dataset.eligible_cases()
    )
    split_counts = {split: _count_split(dataset, split) for split in REQUIRED_SPLITS}
    return {
        "manifest_version": dataset.schema_version,
        "dataset_id": dataset.dataset_version,
        "total": len(dataset.cases),
        "eligible_total": eligible_total,
        "private_real_eligible_total": private_real_eligible_total,
        "blocked_total": len(dataset.cases) - eligible_total,
        "split_counts": split_counts,
        "consent_status_counts": dict(sorted(consent_counts.items())),
        "annotation_status_counts": dict(sorted(annotation_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "minimum_required": MINIMUM_REQUIRED,
        "minimum_met": (
            dataset.schema_version == "2.0"
            and synthetic_release_cases == 0
            and private_real_eligible_total >= MINIMUM_REQUIRED
            and all(counts["eligible"] > 0 for counts in split_counts.values())
        ),
        "checked_at": checked_at or datetime.now(timezone.utc),
    }
