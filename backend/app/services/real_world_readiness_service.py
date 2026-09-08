"""真实案例清单的只读就绪度聚合。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evals.real_world import DatasetValidationError, RealWorldDataset, load_case_manifest


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
    """读取并聚合真实案例治理状态，不返回案例内容或资产信息。"""
    try:
        resolved_manifest = Path(manifest_path).resolve()
        resolved_asset_root = asset_root
        if resolved_asset_root is None and resolved_manifest == DEFAULT_MANIFEST_PATH.resolve():
            resolved_asset_root = DEFAULT_ASSET_ROOT
        dataset = load_case_manifest(resolved_manifest, asset_root=resolved_asset_root)
    except (DatasetValidationError, OSError, ValueError) as exc:
        raise RealWorldReadinessError("真实案例清单不可用") from exc

    consent_counts = Counter(case.consent_status for case in dataset.cases)
    annotation_counts = Counter(case.annotation_status for case in dataset.cases)
    blocker_counts = Counter(
        reason
        for case in dataset.cases
        for reason in case.ineligible_reasons()
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
    split_counts = {
        split: _count_split(dataset, split) for split in REQUIRED_SPLITS
    }
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
