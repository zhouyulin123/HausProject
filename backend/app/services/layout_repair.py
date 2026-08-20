"""布局确定性修复器：针对评分器的硬错误/低分项做局部调整。

修复策略全部是确定性启发式，不依赖 LLM：
- 越界：把家具中心夹回房间（考虑完整占地）。
- 碰撞：把后放置的家具沿候选偏移向量移动，直到不再与对方重叠且不越界。
- 门窗遮挡：把家具沿墙方向移出门口净空区。
- 观看距离：调整电视柜的纵深位置进入合理范围（房间够大时）。

generate → evaluate → repair → 重新评估，最多迭代 max_rounds 轮。
"""

from __future__ import annotations

from math import hypot

from app.schemas.scenes import SceneDocument
from app.services.layout_evaluator import (
    VIEWING_DISTANCE_MAX,
    VIEWING_DISTANCE_MIN,
    LayoutIssue,
    evaluate_layout,
)
from app.services.scene_geometry import (
    door_clearance_polygon,
    item_footprint,
    point_in_polygon,
    polygons_overlap,
)

MAX_REPAIR_ROUNDS = 3
REPAIR_STEP = 0.2

# 候选避让偏移（沿 x/z，米），按优先顺序尝试；幅度覆盖常见家具半宽
_CANDIDATE_OFFSETS = [
    (REPAIR_STEP, 0.0),
    (-REPAIR_STEP, 0.0),
    (0.0, REPAIR_STEP),
    (0.0, -REPAIR_STEP),
    (0.5, 0.0),
    (-0.5, 0.0),
    (0.0, 0.5),
    (0.0, -0.5),
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (2 * REPAIR_STEP, 2 * REPAIR_STEP),
    (-2 * REPAIR_STEP, -2 * REPAIR_STEP),
]

def _clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        return (minimum + maximum) / 2
    return max(minimum, min(maximum, value))


def _room_bounds(scene: SceneDocument) -> tuple[float, float, float, float]:
    xs = [p.x for p in scene.room.floor_polygon]
    zs = [p.z for p in scene.room.floor_polygon]
    return min(xs), max(xs), min(zs), max(zs)


def _room_polygon(scene: SceneDocument) -> list[tuple[float, float]]:
    return [(p.x, p.z) for p in scene.room.floor_polygon]


def _item_by_id(scene: SceneDocument, instance_id: str):
    return next(
        (item for item in scene.items if item.instance_id == instance_id),
        None,
    )


def _fix_out_of_bounds(scene: SceneDocument, item) -> bool:
    """把家具完整占地夹回房间内；家具过大无法夹回时返回 False。"""
    footprint = item_footprint(item)
    if footprint is None:
        return False
    polygon = _room_polygon(scene)
    min_x, max_x, min_z, max_z = _room_bounds(scene)
    half_w = (max(p[0] for p in footprint) - min(p[0] for p in footprint)) / 2
    half_d = (max(p[1] for p in footprint) - min(p[1] for p in footprint)) / 2
    if half_w * 2 >= max_x - min_x or half_d * 2 >= max_z - min_z:
        return False

    item.transform.position.x = _clamp(
        item.transform.position.x, min_x + half_w + 0.05, max_x - half_w - 0.05
    )
    item.transform.position.z = _clamp(
        item.transform.position.z, min_z + half_d + 0.05, max_z - half_d - 0.05
    )
    return True


def _find_non_colliding_position(scene, mover, fixed) -> bool:
    """把 mover 沿候选偏移移动，直到不与 fixed 重叠且不越界。"""
    original_x = mover.transform.position.x
    original_z = mover.transform.position.z
    fixed_footprint = item_footprint(fixed)
    polygon = _room_polygon(scene)
    if fixed_footprint is None:
        return False
    for dx, dz in _CANDIDATE_OFFSETS:
        mover.transform.position.x = original_x + dx
        mover.transform.position.z = original_z + dz
        mover_footprint = item_footprint(mover)
        if mover_footprint is None:
            continue
        if polygons_overlap(mover_footprint, fixed_footprint):
            continue
        if not all(point_in_polygon(p, polygon) for p in mover_footprint):
            continue
        return True
    # 全部候选失败：回到原始位置
    mover.transform.position.x = original_x
    mover.transform.position.z = original_z
    return False


def _fix_collision(scene, first_id: str, second_id: str) -> bool:
    first = _item_by_id(scene, first_id)
    second = _item_by_id(scene, second_id)
    if first is None or second is None:
        return False
    # 移动后放置的家具（索引大）
    first_index = next(
        i for i, item in enumerate(scene.items) if item.instance_id == first_id
    )
    second_index = next(
        i for i, item in enumerate(scene.items) if item.instance_id == second_id
    )
    if first_index < second_index:
        mover, fixed = second, first
    else:
        mover, fixed = first, second
    return _find_non_colliding_position(scene, mover, fixed)


def _fix_door_blocked(scene, item, opening) -> bool:
    """把占用门口净空区的家具沿墙方向移出净空区。"""
    polygon = _room_polygon(scene)
    start = polygon[opening.wall_index]
    end = polygon[(opening.wall_index + 1) % len(polygon)]
    wall_length = hypot(end[0] - start[0], end[1] - start[1])
    if wall_length <= 1e-9:
        return False
    tangent = (
        (end[0] - start[0]) / wall_length,
        (end[1] - start[1]) / wall_length,
    )

    original_x = item.transform.position.x
    original_z = item.transform.position.z
    for step in (
        REPAIR_STEP,
        -REPAIR_STEP,
        2 * REPAIR_STEP,
        -2 * REPAIR_STEP,
    ):
        item.transform.position.x = original_x + tangent[0] * step
        item.transform.position.z = original_z + tangent[1] * step
        clearance = door_clearance_polygon(
            polygon,
            wall_index=opening.wall_index,
            offset=opening.offset,
            width=opening.width,
        )
        footprint = item_footprint(item)
        if footprint is None:
            continue
        if not polygons_overlap(clearance, footprint):
            return True
    item.transform.position.x = original_x
    item.transform.position.z = original_z
    return False


def _fix_viewing_distance(scene, tv_id: str, sofa_id: str) -> bool:
    tv = _item_by_id(scene, tv_id)
    sofa = _item_by_id(scene, sofa_id)
    if tv is None or sofa is None:
        return False
    polygon = _room_polygon(scene)
    footprint = item_footprint(tv)
    if footprint is None:
        return False
    half_d = (max(p[1] for p in footprint) - min(p[1] for p in footprint)) / 2
    min_z, max_z = _room_bounds(scene)[2], _room_bounds(scene)[3]

    current = abs(tv.transform.position.z - sofa.transform.position.z)
    if VIEWING_DISTANCE_MIN <= current <= VIEWING_DISTANCE_MAX:
        return False
    target = (
        VIEWING_DISTANCE_MIN
        if current < VIEWING_DISTANCE_MIN
        else VIEWING_DISTANCE_MAX
    )
    # 电视柜沿远离沙发的方向调整纵深
    sign = 1.0 if tv.transform.position.z >= sofa.transform.position.z else -1.0
    new_z = sofa.transform.position.z + sign * target
    new_z = _clamp(new_z, min_z + half_d + 0.05, max_z - half_d - 0.05)
    if abs(new_z - sofa.transform.position.z) < VIEWING_DISTANCE_MIN:
        return False
    tv.transform.position.z = new_z
    return True


def _apply_repairs(scene: SceneDocument, issues: list[LayoutIssue]) -> None:
    """就地应用一轮确定性修复。"""
    # 1. 越界（最高优先级）
    for issue in issues:
        if issue.code in {"out_of_room", "exceeds_room"} and issue.item_id:
            item = _item_by_id(scene, issue.item_id)
            if item is not None:
                _fix_out_of_bounds(scene, item)

    # 2. 碰撞
    for issue in issues:
        if issue.code == "collision" and issue.item_id:
            # item_id 格式：两个 instanceId 用逗号分隔
            ids = [part for part in (issue.item_id or "").split(",") if part]
            if len(ids) == 2:
                _fix_collision(scene, ids[0], ids[1])

    # 3. 门窗遮挡
    for issue in issues:
        if issue.code == "blocks_door" and issue.item_id:
            item = _item_by_id(scene, issue.item_id)
            opening = next(
                (
                    o
                    for o in scene.openings
                    if issue.message and o.id in issue.message
                ),
                None,
            )
            if item is not None and opening is not None:
                _fix_door_blocked(scene, item, opening)

    # 4. 观看距离
    for issue in issues:
        if issue.code == "viewing_distance" and issue.item_id:
            sofa = next(
                (
                    item
                    for item in scene.items
                    if item.category in {"沙发", "休闲椅"}
                ),
                None,
            )
            if sofa is not None:
                _fix_viewing_distance(scene, issue.item_id, sofa.instance_id)


def repair_layout(
    scene: SceneDocument,
    *,
    max_rounds: int = MAX_REPAIR_ROUNDS,
) -> tuple[SceneDocument, "object"]:
    """对场景做确定性修复并返回 (修复后场景, 最终评分)。

    只要还存在可修复的评分项（硬错误或软问题如观看距离），就持续修复；
    无法消除的项（如家具本身过大）在 max_rounds 后停止。
    """
    current = scene.model_copy(deep=True)
    for _ in range(max_rounds):
        score = evaluate_layout(current)
        if not score.issues:
            return current, score
        _apply_repairs(current, score.issues)
    final_score = evaluate_layout(current)
    return current, final_score
