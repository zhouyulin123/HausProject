from copy import deepcopy
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    DesignPlanVersion,
    DesignRevision,
    DesignTask,
    QuoteSnapshot,
)


def persist_generation(
    db: Session,
    *,
    task: DesignTask,
    plans: list[dict[str, Any]],
    generator: str,
    image_context: list[str] | None = None,
    workflow_trace: list[dict[str, Any]] | None = None,
) -> DesignRevision:
    """把一次生成保存为不可变版本；事务由调用方统一提交。"""
    latest_version = db.scalar(
        select(func.max(DesignRevision.version)).where(
            DesignRevision.task_id == task.id
        )
    )
    revision = DesignRevision(
        task_id=task.id,
        version=(latest_version or 0) + 1,
        requirement_snapshot=deepcopy(task.confirmed_requirement_json or {}),
        image_context_snapshot=deepcopy(image_context or []),
        workflow_trace_snapshot=deepcopy(workflow_trace or []),
        generator=generator,
        status="completed",
    )
    db.add(revision)
    db.flush()

    for index, raw_plan in enumerate(plans):
        plan = deepcopy(raw_plan)
        plan_key = str(plan.get("id") or f"plan-{index + 1}")
        plan_version = DesignPlanVersion(
            revision_id=revision.id,
            plan_key=plan_key,
            plan_name=str(plan.get("name") or f"方案 {index + 1}"),
            style=str(plan.get("style") or "") or None,
            plan_json=plan,
        )
        db.add(plan_version)
        db.flush()

        quote = deepcopy(plan.get("shopQuote") or {})
        db.add(
            QuoteSnapshot(
                plan_version_id=plan_version.id,
                currency="CNY",
                furniture_total=int(quote.get("furnitureTotal") or 0),
                custom_total=int(quote.get("customTotal") or 0),
                grand_total=int(quote.get("total") or 0),
                quote_json=quote,
            )
        )

    db.flush()
    return revision


def get_revision(
    db: Session,
    *,
    task_id: int,
    version: int,
) -> DesignRevision | None:
    return db.scalars(
        select(DesignRevision)
        .options(
            selectinload(DesignRevision.plans).selectinload(
                DesignPlanVersion.quote_snapshot
            )
        )
        .where(
            DesignRevision.task_id == task_id,
            DesignRevision.version == version,
        )
    ).first()


def get_latest_revision(db: Session, *, task_id: int) -> DesignRevision | None:
    return db.scalars(
        select(DesignRevision)
        .options(
            selectinload(DesignRevision.plans).selectinload(
                DesignPlanVersion.quote_snapshot
            )
        )
        .where(DesignRevision.task_id == task_id)
        .order_by(DesignRevision.version.desc())
    ).first()


def list_revisions(db: Session, *, task_id: int) -> list[DesignRevision]:
    return list(
        db.scalars(
            select(DesignRevision)
            .options(
                selectinload(DesignRevision.plans).selectinload(
                    DesignPlanVersion.quote_snapshot
                )
            )
            .where(DesignRevision.task_id == task_id)
            .order_by(DesignRevision.version.desc())
        )
    )


def get_latest_plan(
    db: Session,
    *,
    task_id: int,
    plan_key: str,
) -> DesignPlanVersion | None:
    return db.scalars(
        select(DesignPlanVersion)
        .join(
            DesignRevision,
            DesignRevision.id == DesignPlanVersion.revision_id,
        )
        .where(
            DesignRevision.task_id == task_id,
            DesignPlanVersion.plan_key == plan_key,
        )
        .order_by(DesignRevision.version.desc())
    ).first()


def list_user_designs(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    """列出登录用户的设计任务，每个任务附带最新版本的三套方案快照。"""
    tasks = db.scalars(
        select(DesignTask)
        .where(DesignTask.user_id == user_id)
        .order_by(DesignTask.id.desc())
    ).all()

    result: list[dict[str, Any]] = []
    for task in tasks:
        revision = get_latest_revision(db, task_id=task.id)
        if not revision:
            continue
        plans = []
        for plan_version in revision.plans:
            plan = deepcopy(plan_version.plan_json or {})
            plan["planVersionId"] = plan_version.id
            plan["planKey"] = plan_version.plan_key
            plan["task_id"] = task.id
            plans.append(plan)
        result.append(
            {
                "task_id": task.id,
                "created_at": (
                    task.created_at.strftime("%Y-%m-%d %H:%M")
                    if task.created_at
                    else None
                ),
                "style": task.style,
                "space_type": task.space_type,
                "plans": plans,
            }
        )
    return result


def get_plan_version_for_user(
    db: Session,
    *,
    plan_version_id: int,
    user_id: int,
) -> DesignPlanVersion | None:
    """按方案版本 ID 查询，且该方案必须归属指定登录用户。"""
    return db.scalars(
        select(DesignPlanVersion)
        .options(selectinload(DesignPlanVersion.quote_snapshot))
        .join(
            DesignRevision,
            DesignRevision.id == DesignPlanVersion.revision_id,
        )
        .join(DesignTask, DesignTask.id == DesignRevision.task_id)
        .where(
            DesignPlanVersion.id == plan_version_id,
            DesignTask.user_id == user_id,
        )
    ).first()


def plan_version_payload(plan_version: DesignPlanVersion) -> dict[str, Any]:
    """把方案版本快照转成给前端详情页的结构。"""
    plan = deepcopy(plan_version.plan_json or {})
    plan["planVersionId"] = plan_version.id
    plan["planKey"] = plan_version.plan_key
    return plan
