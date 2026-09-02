"""方案生成请求的规范化摘要与 Agent 操作键。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DesignTask, UploadedImage
from app.services import (
    catalog_service,
    generation_provenance,
    profile_service,
    task_service,
)


def build_request_digest(
    db: Session,
    task: DesignTask,
    *,
    requirement: dict[str, Any] | None = None,
    agent_state_version: int | None = None,
    active_mode: str | None = None,
) -> str:
    """摘要覆盖 Worker 实际读取的任务事实、画像、图片和商品上下文。"""
    normalized_requirement = requirement
    if normalized_requirement is None:
        normalized_requirement = (
            task.confirmed_requirement_json
            or task_service.parse_requirement(task.raw_user_input or "")
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
    return generation_provenance.canonical_digest(
        {
            "schema_version": 1,
            "task_id": task.id,
            "agent_state_version": (
                task.agent_state_version
                if agent_state_version is None
                else agent_state_version
            )
            or 0,
            "active_mode": active_mode or task.active_mode,
            "requirement": normalized_requirement,
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
            "catalog_context": catalog_service.build_catalog_context(db),
        }
    )


def build_agent_operation_key(*, task_id: int, request_digest: str) -> str:
    """从不可变输入摘要派生稳定且满足 API 长度约束的操作键。"""
    digest_value = request_digest.removeprefix("sha256:")
    return f"agent-generation:{task_id}:{digest_value[:40]}"
