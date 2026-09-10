from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.real_world_governance_service import (
    RealWorldGovernanceNotFound,
    RealWorldGovernanceValidationError,
)
from evals.annotations import AnnotationValidationError, load_execution_review
from evals.real_world import EvaluationInputError, RealWorldDataset


def _empty_dataset(*, governance_digest: str | None = None) -> RealWorldDataset:
    return RealWorldDataset(
        schema_version="2.0",
        dataset_version="governance-2026-09-10.1",
        cases=(),
        governance_manifest_digest=governance_digest,
    )


def _enable_protected_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REAL_WORLD_PROTECTED_EVAL", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("REAL_WORLD_RUNNER_ENVIRONMENT", "self-hosted")


def test_governed_source_uses_configured_database_and_upload_root(
    monkeypatch,
    tmp_path,
):
    from evals import dataset_source

    _enable_protected_runner(monkeypatch)
    configured_root = tmp_path / "configured-uploads"
    configured_root.mkdir()
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    db = object()
    expected = _empty_dataset(governance_digest="sha256:" + "a" * 64)
    observed = {}

    monkeypatch.setattr(dataset_source, "settings", SimpleNamespace(upload_dir=str(configured_root)))
    monkeypatch.setattr(dataset_source, "SessionLocal", lambda: nullcontext(db))

    def load_frozen(received_db, version, *, upload_root):
        observed.update(db=received_db, version=version, upload_root=upload_root)
        return expected

    monkeypatch.setattr(dataset_source, "load_frozen_dataset_for_evaluation", load_frozen)

    loaded, dataset_root = dataset_source.load_dataset_source(
        manifest=None,
        dataset_version="governance-2026-09-10.1",
        asset_root=None,
        review_root=review_root,
    )

    assert loaded is expected
    assert dataset_root == review_root.resolve()
    assert observed == {
        "db": db,
        "version": "governance-2026-09-10.1",
        "upload_root": configured_root.resolve(),
    }


def test_governed_source_fails_before_opening_database_outside_protected_runner(
    monkeypatch,
):
    from evals import dataset_source

    monkeypatch.delenv("REAL_WORLD_PROTECTED_EVAL", raising=False)
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return nullcontext(object())

    monkeypatch.setattr(dataset_source, "SessionLocal", session_factory)

    with pytest.raises(EvaluationInputError, match="受保护"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=None,
            review_root=Path.cwd(),
        )

    assert opened is False


def test_governed_source_rejects_github_hosted_ci_before_opening_database(
    monkeypatch,
):
    from evals import dataset_source

    _enable_protected_runner(monkeypatch)
    monkeypatch.setenv("REAL_WORLD_RUNNER_ENVIRONMENT", "github-hosted")
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return nullcontext(object())

    monkeypatch.setattr(dataset_source, "SessionLocal", session_factory)

    with pytest.raises(EvaluationInputError, match="self-hosted"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=None,
            review_root=Path.cwd(),
        )

    assert opened is False


@pytest.mark.parametrize(
    "error",
    [
        RealWorldGovernanceNotFound("冻结数据集不存在"),
        RealWorldGovernanceValidationError("冻结案例授权证据不一致或已失效"),
        RealWorldGovernanceValidationError("冻结案例资产文件摘要不一致"),
    ],
)
def test_governed_source_maps_missing_expired_and_tampered_revisions_to_input_error(
    monkeypatch,
    tmp_path,
    error,
):
    from evals import dataset_source

    _enable_protected_runner(monkeypatch)
    monkeypatch.setattr(dataset_source, "settings", SimpleNamespace(upload_dir=str(tmp_path)))
    monkeypatch.setattr(dataset_source, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(
        dataset_source,
        "load_frozen_dataset_for_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(EvaluationInputError, match="冻结数据集不可用"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=None,
            review_root=tmp_path,
        )


def test_dataset_version_rejects_static_asset_root(monkeypatch, tmp_path):
    from evals import dataset_source

    _enable_protected_runner(monkeypatch)

    with pytest.raises(EvaluationInputError, match="asset-root"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=tmp_path,
            review_root=tmp_path,
        )


def test_governed_source_requires_an_existing_review_root_before_database_access(
    monkeypatch,
    tmp_path,
):
    from evals import dataset_source

    _enable_protected_runner(monkeypatch)
    opened = False

    def session_factory():
        nonlocal opened
        opened = True
        return nullcontext(object())

    monkeypatch.setattr(dataset_source, "SessionLocal", session_factory)

    with pytest.raises(EvaluationInputError, match="review-root"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=None,
            review_root=None,
        )
    with pytest.raises(EvaluationInputError, match="review-root"):
        dataset_source.load_dataset_source(
            manifest=None,
            dataset_version="governance-2026-09-10.1",
            asset_root=None,
            review_root=tmp_path / "missing",
        )

    assert opened is False


def test_execution_review_cannot_escape_governed_review_root(tmp_path):
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    outside = tmp_path / "outside-review.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(AnnotationValidationError, match="目录之外"):
        load_execution_review(
            outside,
            dataset=_empty_dataset(),
            dataset_root=review_root,
            expected_output_digest="sha256:" + "a" * 64,
            expected_sha256="b" * 64,
        )
