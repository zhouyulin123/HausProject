"""确定性布局评分器：衡量一个 SceneDocument 的布局设计质量。

与 scene_service.validate_scene 的「数据完整性 / 空间安全」不同，
这里评估「设计质量」：尺寸适配、观看距离、碰撞、门窗遮挡等。
评分为扣分制（满分 100），结果用于候选布局选优与 repair 触发。
"""

from dataclasses import dataclass, field
from itertools import combinations

from app.schemas.scenes import SceneDocument
from app.services.scene_geometry import (
    NON_BLOCKING_CATEGORIES,
    door_clearance_polygon,
    item_footprint,
    point_in_polygon,
    polygons_overlap,
    vertical_ranges_overlap,
)

# 评分低于该值视为不合格，需要 repair
PASS_THRESHOLD = 60

# 一旦出现即为硬错误（空间安全级），布局直接判定不合格
HARD_FAIL_CODES = {"out_of_room", "exceeds_room", "collision", "blocks_door"}

# 沙发到对面柜体的合理观看距离范围（米）
VIEWING_DISTANCE_MIN = 2.0
VIEWING_DISTANCE_MAX = 5.0
# 沙发与电视柜在 x 轴上的对齐容差（米）
VIEWING_ALIGNMENT_TOLERANCE = 1.5
# 家具相对房间需要保留的通道余量（米）
CHANNEL_MARGIN = 0.6


@dataclass
class LayoutIssue:
    code: str
    message: str
    item_id: str | None = None
    penalty: int = 0


@dataclass
class LayoutScore:
    total: int = 100
    issues: list[LayoutIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        if any(issue.code in HARD_FAIL_CODES for issue in self.issues):
            return False
        return self.total >= PASS_THRESHOLD


def _room_polygon(scene: SceneDocument) -> list[tuple[float, float]]:
    return [(p.x, p.z) for p in scene.room.floor_polygon]


def _physical_items(scene: SceneDocument) -> list:
    return [
        item
        for item in scene.items
        if item.category not in NON_BLOCKING_CATEGORIES
    ]


def _footprint_extent(footprint: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in footprint]
    zs = [p[1] for p in footprint]
    return max(xs) - min(xs), max(zs) - min(zs)


def evaluate_layout(scene: SceneDocument) -> LayoutScore:
    """确定性评估一个已摆放家具的场景布局。

    所有规则均为纯计算，不调用 LLM；结果可直接解释。
    """
    score = LayoutScore()
    issues: list[LayoutIssue] = []
    polygon = _room_polygon(scene)

    # ---- 1. 越界：中心点与完整占地都必须位于房间内
    for item in scene.items:
        position = item.transform.position
        if not point_in_polygon((position.x, position.z), polygon):
            issues.append(
                LayoutIssue(
                    "out_of_room",
                    f"{item.instance_id} 中心点位于房间外",
                    item.instance_id,
                    20,
                )
            )
            continue
        footprint = item_footprint(item)
        if footprint and not all(
            point_in_polygon(point, polygon) for point in footprint
        ):
            issues.append(
                LayoutIssue(
                    "exceeds_room",
                    f"{item.instance_id} 完整占地超出房间",
                    item.instance_id,
                    20,
                )
            )

    # ---- 2. 碰撞：垂直区间重叠的物理家具占地不能相交
    physical = _physical_items(scene)
    for first, second in combinations(physical, 2):
        first_footprint = item_footprint(first)
        second_footprint = item_footprint(second)
        if (
            first_footprint
            and second_footprint
            and vertical_ranges_overlap(first, second)
            and polygons_overlap(first_footprint, second_footprint)
        ):
            issues.append(
                LayoutIssue(
                    "collision",
                    f"{first.instance_id} 与 {second.instance_id} 发生占地碰撞",
                    f"{first.instance_id},{second.instance_id}",
                    15,
                )
            )

    # ---- 3. 门窗遮挡：家具不得占用门/洞口内侧净空
    for opening in scene.openings:
        if opening.type not in {"door", "passage"}:
            continue
        clearance = door_clearance_polygon(
            polygon,
            wall_index=opening.wall_index,
            offset=opening.offset,
            width=opening.width,
        )
        for item in physical:
            footprint = item_footprint(item)
            if footprint and polygons_overlap(clearance, footprint):
                issues.append(
                    LayoutIssue(
                        "blocks_door",
                        f"{item.instance_id} 占用了洞口 {opening.id} 动线",
                        item.instance_id,
                        25,
                    )
                )

    # ---- 4. 观看距离：正对的沙发与柜体间距应在合理范围
    sofa = next(
        (item for item in scene.items if item.category in {"沙发", "休闲椅"}),
        None,
    )
    cabinet = None
    if sofa is not None:
        for item in scene.items:
            if item.category not in {"柜子", "电视柜", "边柜"}:
                continue
            dx = abs(item.transform.position.x - sofa.transform.position.x)
            if dx <= VIEWING_ALIGNMENT_TOLERANCE:
                cabinet = item
                break
    if sofa is not None and cabinet is not None:
        distance = abs(cabinet.transform.position.z - sofa.transform.position.z)
        if not (VIEWING_DISTANCE_MIN <= distance <= VIEWING_DISTANCE_MAX):
            issues.append(
                LayoutIssue(
                    "viewing_distance",
                    f"柜体到沙发距离 {distance:.1f} 米，"
                    f"合理范围 {VIEWING_DISTANCE_MIN}~{VIEWING_DISTANCE_MAX} 米",
                    cabinet.instance_id,
                    10,
                )
            )

    # ---- 5. 尺寸适配：家具占地不应挤占整间房的主通道
    room_width = max(p[0] for p in polygon) - min(p[0] for p in polygon)
    room_depth = max(p[1] for p in polygon) - min(p[1] for p in polygon)
    for item in scene.items:
        footprint = item_footprint(item)
        if not footprint:
            continue
        item_width, item_depth = _footprint_extent(footprint)
        if item_width > room_width - CHANNEL_MARGIN or (
            item_depth > room_depth - CHANNEL_MARGIN
        ):
            issues.append(
                LayoutIssue(
                    "oversized",
                    f"{item.instance_id} 尺寸相对房间过大，会挤占通道",
                    item.instance_id,
                    5,
                )
            )

    score.issues = issues
    score.total = max(0, 100 - sum(issue.penalty for issue in issues))
    return score
