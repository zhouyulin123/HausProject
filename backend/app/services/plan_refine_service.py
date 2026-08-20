"""方案精修编排：把「自然语言修改指令」落到新的不可变方案版本上。"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agents.plan_refine_agent import (
    PlanRefineQualityError,
    PlanRefineWorkflow,
)
from app.db.models import DesignTask
from app.services import (
    catalog_service,
    design_version_service,
    llm_service,
    profile_service,
    scene_service,
)
from app.services.llm_service import LLMUnavailable

logger = logging.getLogger(__name__)


class PlanRefineError(ValueError):
    """方案精修失败（供路由层转成 HTTP 错误）。"""


def refine_plan_version(
    db: Session,
    *,
    task: DesignTask,
    plan_id: str,
    instruction: str,
) -> dict[str, Any]:
    """在最新版本上按指令修改 plan_id 对应方案，写入新的不可变版本。

    返回 {plan, version, message}，其中 plan 含新的 planVersionId。
    """
    revision = design_version_service.get_latest_revision(db, task_id=task.id)
    if revision is None:
        raise PlanRefineError("该任务还没有生成方案")

    target = next(
        (p for p in revision.plans if p.plan_key == plan_id),
        None,
    )
    if target is None:
        raise PlanRefineError("未找到要修改的方案")

    current_plan = deepcopy(target.plan_json or {})
    catalog_context = catalog_service.build_catalog_context(db)

    workflow = PlanRefineWorkflow(
        refine_plan=llm_service.refine_plan,
        enrich_plans=lambda plans: catalog_service.verify_and_enrich_plans(
            db,
            plans,
        ),
    )
    try:
        result = workflow.run(
            instruction=instruction,
            current_plan=current_plan,
            catalog_context=catalog_context,
        )
    except LLMUnavailable as exc:
        raise PlanRefineError("AI 设计服务暂时不可用，请稍后重试") from exc
    except PlanRefineQualityError as exc:
        raise PlanRefineError(str(exc)) from exc

    refined_plan = result["refined_plan"]
    message = result["message"]

    # 组装新版本的三套方案：被修改的替换，其余保持原样（按 plan_key 排序）
    plans: list[dict[str, Any]] = []
    for plan_version in sorted(revision.plans, key=lambda p: p.plan_key):
        if plan_version.plan_key == plan_id:
            plans.append(refined_plan)
        else:
            plans.append(deepcopy(plan_version.plan_json or {}))

    new_revision = design_version_service.persist_generation(
        db,
        task=task,
        plans=plans,
        generator="refine",
        image_context=deepcopy(revision.image_context_snapshot or []),
        workflow_trace=[{"node": "plan_refine", "status": "completed"}],
    )
    db.commit()

    # 登录用户：从修改指令中学习偏好（如预算敏感、材质偏好），不阻断主流程
    if task.user_id:
        try:
            profile_service.extract_and_merge(
                db,
                user_id=task.user_id,
                text=instruction,
            )
        except Exception:
            logger.exception("画像提取失败: task_id=%s", task.id)

    refreshed = design_version_service.get_latest_revision(db, task_id=task.id)
    new_target = next(
        (p for p in refreshed.plans if p.plan_key == plan_id),
        None,
    )
    if new_target is None:
        raise PlanRefineError("方案修改写入失败")

    # 继承 3D 场景：旧版本已有场景时，把场景归属移到新版本，保留用户家具布局
    old_scene = scene_service.get_scene_by_plan_version(db, target.id)
    if old_scene is not None:
        old_scene.plan_version_id = new_target.id
        db.commit()

    plan_payload = design_version_service.plan_version_payload(new_target)
    plan_payload["task_id"] = task.id
    return {
        "plan": plan_payload,
        "version": new_revision.version,
        "message": message or "已按你的要求调整方案",
    }
