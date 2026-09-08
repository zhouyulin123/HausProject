"""仅基于冻结 SceneDocument 复算真实案例布局硬约束。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Literal

from app.schemas.scenes import SceneDocument
from app.services.scene_geometry import (
    NON_BLOCKING_CATEGORIES,
    door_clearance_polygon,
    item_footprint,
    point_in_polygon,
    polygons_overlap,
    vertical_ranges_overlap,
)
from evals.annotations import LayoutHardConstraint


EvidenceStatus = Literal["passed", "failed", "no_evidence"]

# SceneDocument does not freeze a walkable-area graph or an occupancy model.
# Keep these names readable for legacy input, but never admit them into a new
# trusted annotation until the scene contract contains those facts.
UNREPRESENTED_LAYOUT_CONSTRAINT_TYPES = frozenset(
    {"walkway_width", "maximum_occupancy"}
)
SUPPORTED_LAYOUT_CONSTRAINT_TYPES = frozenset(
    {
        "minimum_clearance",
        "inside_room",
        "no_overlap",
        "door_swing_clearance",
        "wall_offset",
    }
)


@dataclass(frozen=True)
class LayoutConstraintEvidence:
    status: EvidenceStatus
    reason_code: str


def validate_layout_constraint_for_admission(
    constraint: LayoutHardConstraint,
) -> None:
    """拒绝无法由冻结 SceneDocument 复算的标注约束。"""
    if constraint.type in UNREPRESENTED_LAYOUT_CONSTRAINT_TYPES:
        raise ValueError(
            "layout_hard_constraints 包含无法由冻结 SceneDocument "
            "确定性评估的约束类型："
            f"{constraint.type}"
        )


def _compare(actual: float, operator: str, expected: float) -> bool:
    epsilon = 1e-6
    if operator == "gte":
        return actual + epsilon >= expected
    if operator == "lte":
        return actual <= expected + epsilon
    return abs(actual - expected) <= epsilon


def _point_segment_distance(point, start, end) -> float:
    dx = end[0] - start[0]
    dz = end[1] - start[1]
    length_squared = dx * dx + dz * dz
    if length_squared <= 1e-12:
        return hypot(point[0] - start[0], point[1] - start[1])
    projection = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
            / length_squared,
        ),
    )
    nearest = (start[0] + projection * dx, start[1] + projection * dz)
    return hypot(point[0] - nearest[0], point[1] - nearest[1])


def _polygon_distance(first, second) -> float:
    if polygons_overlap(first, second):
        return 0.0
    distances = []
    for polygon, other in ((first, second), (second, first)):
        edges = list(zip(other, other[1:] + other[:1]))
        distances.extend(
            _point_segment_distance(point, start, end)
            for point in polygon
            for start, end in edges
        )
    return min(distances)


def _inside_room(scene: SceneDocument, constraint: LayoutHardConstraint):
    if constraint.operator != "eq" or not isinstance(constraint.value, bool):
        return LayoutConstraintEvidence("no_evidence", "boolean_contract_required")
    item = next(
        (item for item in scene.items if item.instance_id == constraint.subject_id),
        None,
    )
    if item is None:
        return LayoutConstraintEvidence("no_evidence", "subject_not_found")
    footprint = item_footprint(item)
    if footprint is None:
        return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
    polygon = [(point.x, point.z) for point in scene.room.floor_polygon]
    actual = all(point_in_polygon(point, polygon) for point in footprint)
    passed = actual == constraint.value
    return LayoutConstraintEvidence(
        "passed" if passed else "failed",
        "inside_room_matched" if passed else "inside_room_violated",
    )


def _no_overlap(scene: SceneDocument, constraint: LayoutHardConstraint):
    if constraint.operator != "eq" or not isinstance(constraint.value, bool):
        return LayoutConstraintEvidence("no_evidence", "boolean_contract_required")
    subject = next(
        (item for item in scene.items if item.instance_id == constraint.subject_id),
        None,
    )
    if subject is None:
        return LayoutConstraintEvidence("no_evidence", "subject_not_found")
    subject_footprint = item_footprint(subject)
    if subject_footprint is None:
        return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
    if constraint.related_id:
        related = next(
            (
                item
                for item in scene.items
                if item.instance_id == constraint.related_id
            ),
            None,
        )
        if related is None:
            return LayoutConstraintEvidence("no_evidence", "related_not_found")
        candidates = [related]
    else:
        candidates = [
            item
            for item in scene.items
            if item.instance_id != subject.instance_id
            and item.category not in NON_BLOCKING_CATEGORIES
        ]
    for related in candidates:
        footprint = item_footprint(related)
        if footprint is None:
            return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
        if vertical_ranges_overlap(subject, related) and polygons_overlap(
            subject_footprint,
            footprint,
        ):
            actual = False
            break
    else:
        actual = True
    passed = actual == constraint.value
    return LayoutConstraintEvidence(
        "passed" if passed else "failed",
        "no_overlap_matched" if passed else "overlap_detected",
    )


def _minimum_clearance(scene: SceneDocument, constraint: LayoutHardConstraint):
    if isinstance(constraint.value, bool) or constraint.unit != "mm":
        return LayoutConstraintEvidence("no_evidence", "millimeter_contract_required")
    if not constraint.related_id:
        return LayoutConstraintEvidence("no_evidence", "related_not_specified")
    by_id = {item.instance_id: item for item in scene.items}
    subject = by_id.get(constraint.subject_id)
    related = by_id.get(constraint.related_id)
    if subject is None or related is None:
        return LayoutConstraintEvidence("no_evidence", "subject_or_related_not_found")
    first = item_footprint(subject)
    second = item_footprint(related)
    if first is None or second is None:
        return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
    actual_mm = _polygon_distance(first, second) * 1000
    passed = _compare(actual_mm, constraint.operator, float(constraint.value))
    return LayoutConstraintEvidence(
        "passed" if passed else "failed",
        "clearance_matched" if passed else "clearance_violated",
    )


def _wall_offset(scene: SceneDocument, constraint: LayoutHardConstraint):
    if isinstance(constraint.value, bool) or constraint.unit != "mm":
        return LayoutConstraintEvidence("no_evidence", "millimeter_contract_required")
    item = next(
        (item for item in scene.items if item.instance_id == constraint.subject_id),
        None,
    )
    if item is None:
        return LayoutConstraintEvidence("no_evidence", "subject_not_found")
    footprint = item_footprint(item)
    if footprint is None:
        return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
    polygon = [(point.x, point.z) for point in scene.room.floor_polygon]
    edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    actual_mm = min(
        _point_segment_distance(point, start, end)
        for point in footprint
        for start, end in edges
    ) * 1000
    passed = _compare(actual_mm, constraint.operator, float(constraint.value))
    return LayoutConstraintEvidence(
        "passed" if passed else "failed",
        "wall_offset_matched" if passed else "wall_offset_violated",
    )


def _door_clearance(scene: SceneDocument, constraint: LayoutHardConstraint):
    if constraint.operator != "eq" or not isinstance(constraint.value, bool):
        return LayoutConstraintEvidence("no_evidence", "boolean_contract_required")
    openings = {opening.id: opening for opening in scene.openings}
    items = {item.instance_id: item for item in scene.items}
    if constraint.subject_id in openings:
        opening = openings[constraint.subject_id]
        candidates = [
            item
            for item in scene.items
            if item.category not in NON_BLOCKING_CATEGORIES
        ]
    elif constraint.related_id in openings and constraint.subject_id in items:
        opening = openings[constraint.related_id]
        candidates = [items[constraint.subject_id]]
    else:
        return LayoutConstraintEvidence("no_evidence", "opening_not_found")
    if opening.type not in {"door", "passage"}:
        return LayoutConstraintEvidence("no_evidence", "opening_has_no_door_clearance")
    polygon = [(point.x, point.z) for point in scene.room.floor_polygon]
    clearance = door_clearance_polygon(
        polygon,
        wall_index=opening.wall_index,
        offset=opening.offset,
        width=opening.width,
    )
    for item in candidates:
        footprint = item_footprint(item)
        if footprint is None:
            return LayoutConstraintEvidence("no_evidence", "dimensions_missing")
        if polygons_overlap(clearance, footprint):
            actual = False
            break
    else:
        actual = True
    passed = actual == constraint.value
    return LayoutConstraintEvidence(
        "passed" if passed else "failed",
        "door_clearance_matched" if passed else "door_clearance_violated",
    )


def evaluate_layout_constraint(
    scene: SceneDocument,
    constraint: LayoutHardConstraint,
) -> LayoutConstraintEvidence:
    """对单条标注给出 passed/failed/no_evidence，绝不使用模型自报值。"""
    if constraint.room_id != scene.room.id:
        return LayoutConstraintEvidence("no_evidence", "room_not_found")
    evaluators = {
        "inside_room": _inside_room,
        "no_overlap": _no_overlap,
        "minimum_clearance": _minimum_clearance,
        "wall_offset": _wall_offset,
        "door_swing_clearance": _door_clearance,
    }
    if constraint.type not in SUPPORTED_LAYOUT_CONSTRAINT_TYPES:
        # Legacy records remain readable, but cannot produce trusted evidence.
        return LayoutConstraintEvidence("no_evidence", "constraint_not_represented")
    evaluator = evaluators.get(constraint.type)
    if evaluator is None:
        return LayoutConstraintEvidence("no_evidence", "constraint_not_represented")
    return evaluator(scene, constraint)
