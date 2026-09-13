"""跨数据库的 DesignTask 聚合根写锁。"""

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import (
    AnonymousSessionTask,
    DesignPlanVersion,
    DesignRevision,
    DesignScene,
    DesignTask,
)


class AggregateLockBusy(ValueError):
    """聚合写锁在等待窗口内未取得，或数据库检测到死锁。"""


def _locked_scalar(db: Session, statement):
    try:
        return db.scalar(statement)
    except OperationalError as exc:
        arguments = getattr(exc.orig, "args", ())
        if db.get_bind().dialect.name == "mysql" and arguments and arguments[0] in {1205, 1213}:
            db.rollback()
            raise AggregateLockBusy("业务状态正在被其他请求更新，请重试") from exc
        raise


def _begin_sqlite_write(db: Session) -> bool:
    if db.get_bind().dialect.name != "sqlite":
        return False
    # 路由的会话/归属检查可能已开启只读事务，先结束后再获取 RESERVED 锁。
    db.commit()
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    except OperationalError as exc:
        db.rollback()
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise AggregateLockBusy("业务状态正在被其他请求更新，请重试") from exc
        raise
    return True


def lock_task(db: Session, task_id: int) -> DesignTask | None:
    """锁定任务聚合根；调用方必须在任何业务事实读取前调用。"""
    sqlite = _begin_sqlite_write(db)
    statement = (
        select(DesignTask)
        .where(DesignTask.id == task_id)
        .execution_options(populate_existing=True)
    )
    if not sqlite:
        statement = statement.with_for_update()
    return _locked_scalar(db, statement)


def lock_owned_task(
    db: Session,
    *,
    session_id: str,
    task_id: int,
) -> DesignTask | None:
    """加锁后重新验证任务归属，避免检查与写入之间发生状态漂移。"""
    sqlite = _begin_sqlite_write(db)
    statement = (
        select(DesignTask)
        .join(
            AnonymousSessionTask,
            AnonymousSessionTask.task_id == DesignTask.id,
        )
        .where(
            DesignTask.id == task_id,
            AnonymousSessionTask.session_id == session_id,
        )
        .execution_options(populate_existing=True)
    )
    if not sqlite:
        statement = statement.with_for_update()
    return _locked_scalar(db, statement)


def lock_owned_scene(
    db: Session,
    *,
    session_id: str,
    scene_id: int,
) -> tuple[DesignTask, DesignScene] | None:
    """按任务根、场景的固定顺序锁定，并在锁内验证场景归属。"""
    sqlite = _begin_sqlite_write(db)
    task_statement = (
        select(DesignTask)
        .join(DesignRevision, DesignRevision.task_id == DesignTask.id)
        .join(
            DesignPlanVersion,
            DesignPlanVersion.revision_id == DesignRevision.id,
        )
        .join(DesignScene, DesignScene.plan_version_id == DesignPlanVersion.id)
        .join(
            AnonymousSessionTask,
            AnonymousSessionTask.task_id == DesignTask.id,
        )
        .where(
            DesignScene.id == scene_id,
            AnonymousSessionTask.session_id == session_id,
        )
        .execution_options(populate_existing=True)
    )
    if not sqlite:
        task_statement = task_statement.with_for_update()
    task = _locked_scalar(db, task_statement)
    if task is None:
        return None

    scene_statement = (
        select(DesignScene)
        .where(DesignScene.id == scene_id)
        .execution_options(populate_existing=True)
    )
    if not sqlite:
        scene_statement = scene_statement.with_for_update()
    scene = _locked_scalar(db, scene_statement)
    return (task, scene) if scene is not None else None
