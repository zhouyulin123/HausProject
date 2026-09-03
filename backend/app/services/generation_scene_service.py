"""在 GenerationRun 成功提交前生成并冻结逐方案 3D 场景。"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import DesignRevision, DesignTask
from app.services import (
    generation_output_service,
    layout_generator,
    layout_service,
    scene_service,
)


def prepare_revision_scenes(
    db: Session,
    *,
    revision_id: int,
) -> None:
    """为 revision 的每个方案创建确定性 v1；已有场景只做存在性校验。"""
    revision = db.get(DesignRevision, revision_id)
    if revision is None or not revision.plans:
        raise generation_output_service.GenerationOutputValidationError(
            "生成输出 revision 不存在或没有方案"
        )
    task = db.get(DesignTask, revision.task_id)
    if task is None:
        raise generation_output_service.GenerationOutputValidationError(
            "生成输出 revision 对应任务不存在"
        )

    for plan in revision.plans:
        existing = scene_service.get_scene_by_plan_version(db, plan.id)
        if existing is not None:
            try:
                scene_service.get_current_version(db, existing)
            except RuntimeError as exc:
                raise generation_output_service.GenerationOutputValidationError(
                    f"方案 {plan.plan_key} 的场景当前版本引用不一致"
                ) from exc
            continue
        furniture = layout_service.build_layout_furniture(
            db,
            (plan.plan_json or {}).get("furnitureSuggestions"),
        )
        if not furniture:
            raise generation_output_service.GenerationOutputValidationError(
                f"方案 {plan.plan_key} 没有可冻结的布局商品"
            )
        geometry = layout_service.room_geometry_from_plan_version(db, plan)
        room_name = task.space_type or "客厅"
        room, openings = geometry or layout_service.default_room_geometry(room_name)
        started = time.monotonic()
        results = layout_generator.generate_layouts(room, openings, furniture)
        if not results:
            raise generation_output_service.GenerationOutputValidationError(
                f"方案 {plan.plan_key} 无法生成确定性布局场景"
            )
        document, best_score = results[0]
        if not best_score.valid:
            issue_codes = list(
                dict.fromkeys(issue.code for issue in best_score.issues)
            )
            reason = ", ".join(issue_codes) or "layout_score_below_threshold"
            raise generation_output_service.GenerationOutputValidationError(
                f"方案 {plan.plan_key} 的最佳布局未通过确定性门禁：{reason}"
            )
        try:
            _, version = scene_service.create_scene(
                db,
                plan_version=plan,
                document=document,
                source="auto_layout",
            )
        except (scene_service.SceneConflictError, scene_service.SceneValidationError) as exc:
            raise generation_output_service.GenerationOutputValidationError(
                f"方案 {plan.plan_key} 的确定性布局场景无法冻结"
            ) from exc
        layout_service.record_layout_run(
            db,
            plan_version_id=plan.id,
            scene_version_id=version.id,
            room=room,
            furniture=furniture,
            results=results,
            duration_ms=int((time.monotonic() - started) * 1000),
            source="generation_worker",
        )
    db.flush()
