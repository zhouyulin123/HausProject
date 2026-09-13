"""正式方案生成来源及派生链校验。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.db.models import DesignRevision


FORMAL_ROOT_SOURCES = frozenset({"llm"})
FORMAL_DERIVED_SOURCES = {
    "refine": "plan_refine",
    "workspace_edit": "workspace_plan_mutation",
}


def validate_source_chain(revision: DesignRevision | None) -> str | None:
    """返回稳定失败码；可信根或完整派生链返回 ``None``。"""
    visited: set[int] = set()
    current = revision
    while current is not None:
        revision_id = getattr(current, "id", None)
        if not isinstance(revision_id, int) or revision_id in visited:
            return "generation_source_chain_invalid"
        visited.add(revision_id)
        source = str(getattr(current, "generator", "") or "").strip().lower()
        if source in FORMAL_ROOT_SOURCES:
            return None
        expected_node = FORMAL_DERIVED_SOURCES.get(source)
        if expected_node is None:
            return "generation_source_untrusted"
        trace = current.workflow_trace_snapshot
        if not isinstance(trace, list):
            return "generation_source_chain_invalid"
        binding = next(
            (
                item
                for item in trace
                if isinstance(item, dict) and item.get("node") == expected_node
            ),
            None,
        )
        if not isinstance(binding, dict):
            return "generation_source_chain_invalid"
        source_revision_id = binding.get("source_revision_id")
        source_revision_version = binding.get("source_revision_version")
        if (
            not isinstance(source_revision_id, int)
            or isinstance(source_revision_id, bool)
            or not isinstance(source_revision_version, int)
            or isinstance(source_revision_version, bool)
        ):
            return "generation_source_chain_invalid"
        session = object_session(current)
        if session is None:
            return "generation_source_chain_invalid"
        parent = session.scalar(
            select(DesignRevision).where(
                DesignRevision.id == source_revision_id,
                DesignRevision.task_id == current.task_id,
                DesignRevision.version == source_revision_version,
                DesignRevision.version < current.version,
                DesignRevision.status == "completed",
            )
        )
        if parent is None:
            return "generation_source_chain_invalid"
        current = parent
    return "generation_source_chain_invalid"
