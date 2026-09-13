"""方案生成请求的规范化摘要与 Agent 操作键。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DesignTask, UploadedImage
from app.services import (
    generation_constraints_service,
    generation_provenance,
    profile_service,
    task_service,
)


def build_request_contract(
    db: Session,
    task: DesignTask,
    *,
    requirement: dict[str, Any] | None = None,
    agent_state_version: int | None = None,
    active_mode: str | None = None,
) -> dict[str, Any]:
    """冻结 Worker 将读取的任务事实及商品、规则版本指纹。"""
    normalized_requirement = requirement
    if normalized_requirement is None:
        normalized_requirement = (
            task.confirmed_requirement_json
            or task_service.parse_requirement(task.raw_user_input or "")
        )
    generation_context = generation_constraints_service.build_generation_context(
        db,
        task,
        requirement=normalized_requirement,
    )
    profile_context = None
    if task.user_id:
        profile = profile_service.get_or_create_profile(db, user_id=task.user_id)
        profile_context = profile_service.build_profile_context(profile) or None
    images = db.scalars(
        select(UploadedImage)
        .where(UploadedImage.task_id == task.id)
        .order_by(UploadedImage.id)
    ).all()
    return {
        "schema_version": 3,
        "task_id": task.id,
        "agent_state_version": (
            task.agent_state_version
            if agent_state_version is None
            else agent_state_version
        )
        or 0,
        "active_mode": active_mode or task.active_mode,
        "requirement": generation_context.requirement,
        "constraints": generation_context.constraints.as_dict(),
        "profile_context": profile_context,
        "images": [
            {
                "id": image.id,
                "image_type": image.image_type,
                "file_url": image.file_url,
                "analysis": image.analysis_json,
            }
            for image in images
        ],
        "catalog_context": generation_context.catalog_context,
        "catalog_fingerprint": generation_context.catalog_fingerprint,
    }


def digest_request_contract(contract: dict[str, Any]) -> str:
    return generation_provenance.canonical_digest(contract)


def build_request_digest(
    db: Session,
    task: DesignTask,
    *,
    requirement: dict[str, Any] | None = None,
    agent_state_version: int | None = None,
    active_mode: str | None = None,
) -> str:
    """摘要覆盖 Worker 实际读取的任务事实、图片和目录版本。"""
    return digest_request_contract(
        build_request_contract(
            db,
            task,
            requirement=requirement,
            agent_state_version=agent_state_version,
            active_mode=active_mode,
        )
    )


def build_agent_operation_key(*, task_id: int, request_digest: str) -> str:
    """从不可变输入摘要派生稳定且满足 API 长度约束的操作键。"""
    digest_value = request_digest.removeprefix("sha256:")
    return f"agent-generation:{task_id}:{digest_value[:40]}"
