from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.schema_readiness import (
    database_schema_is_current,
    expected_migration_heads,
)


class _ScalarResult:
    def __init__(self, revisions: tuple[str, ...]):
        self._revisions = revisions

    def all(self) -> list[str]:
        return list(self._revisions)


class _ExecutionResult:
    def __init__(self, revisions: tuple[str, ...]):
        self._revisions = revisions

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._revisions)


class _Session:
    def __init__(self, revisions: tuple[str, ...]):
        self._revisions = revisions

    def execute(self, _statement) -> _ExecutionResult:
        return _ExecutionResult(self._revisions)


def test_expected_migration_heads_match_alembic_repository():
    backend_root = Path(__file__).resolve().parents[2] / "backend"
    config = Config(str(backend_root / "alembic.ini"))
    expected = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))

    assert expected_migration_heads() == expected


def test_database_schema_is_current_only_for_exact_head_set(monkeypatch):
    monkeypatch.setattr(
        "app.db.schema_readiness.expected_migration_heads",
        lambda: ("head-a", "head-b"),
    )

    assert database_schema_is_current(_Session(("head-b", "head-a"))) is True
    assert database_schema_is_current(_Session(("head-a",))) is False
    assert database_schema_is_current(_Session(("head-a", "unknown"))) is False
    assert database_schema_is_current(_Session(())) is False
