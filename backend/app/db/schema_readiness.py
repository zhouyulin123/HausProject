from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import SessionLocal


_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def expected_migration_heads() -> tuple[str, ...]:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return tuple(sorted(script.get_heads()))


def current_migration_heads(db: Session) -> tuple[str, ...]:
    result = db.execute(text("SELECT version_num FROM alembic_version"))
    return tuple(sorted(str(revision) for revision in result.scalars().all()))


def database_schema_is_current(db: Session) -> bool:
    return current_migration_heads(db) == expected_migration_heads()


def main() -> int:
    try:
        with SessionLocal() as db:
            current = current_migration_heads(db)
        expected = expected_migration_heads()
    except Exception:
        print("database_schema=unavailable")
        return 2

    print("database_schema_current=" + ",".join(current))
    print("database_schema_expected=" + ",".join(expected))
    if current != expected:
        print("database_schema=migration_required")
        return 3

    print("database_schema=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
