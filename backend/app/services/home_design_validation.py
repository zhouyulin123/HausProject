"""确定性盒体校验，不把通过几何校验等同于施工安全认证。"""

from itertools import combinations, islice, chain
from math import cos, sin, radians, hypot
from dataclasses import dataclass

from app.schemas.home_design import DesignIssue, DesignValidation, HomeDesignDocument
from app.schemas.spatial import SpatialDocument, _interiors_overlap

EPS = 1e-8
MAX_ISSUES = 200


@dataclass(frozen=True)
class SpatialPoint:
    x: float
    z: float


def footprint(item):
    angle = radians(item.rotation)
    c, s = cos(angle), sin(angle)
    return [
        SpatialPoint(
            x=item.position.x + x * c + z * s, z=item.position.z - x * s + z * c
        )
        for x, z in [
            (-item.size.width / 2, -item.size.depth / 2),
            (item.size.width / 2, -item.size.depth / 2),
            (item.size.width / 2, item.size.depth / 2),
            (-item.size.width / 2, item.size.depth / 2),
        ]
    ]


def _inside(point, polygon):
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (b.x - a.x) * (point.z - a.z) - (b.z - a.z) * (point.x - a.x)
        if (
            abs(cross) < EPS
            and min(a.x, b.x) - EPS <= point.x <= max(a.x, b.x) + EPS
            and min(a.z, b.z) - EPS <= point.z <= max(a.z, b.z) + EPS
        ):
            return True
        if (a.z > point.z) != (b.z > point.z) and point.x < (b.x - a.x) * (
            point.z - a.z
        ) / (b.z - a.z) + a.x:
            inside = not inside
    return inside


def _contained(box, polygon):
    if not all(_inside(p, polygon) for p in box):
        return False
    # 凹多边形不能只检查四角；将每条盒体边按房间边界交点分段检查。
    for a, b in zip(box, box[1:] + box[:1]):
        dx, dz = b.x - a.x, b.z - a.z
        cuts = [0.0, 1.0]
        for c, d in zip(polygon, polygon[1:] + polygon[:1]):
            ex, ez = d.x - c.x, d.z - c.z
            denominator = dx * ez - dz * ex
            if abs(denominator) > EPS:
                t = ((c.x - a.x) * ez - (c.z - a.z) * ex) / denominator
                u = ((c.x - a.x) * dz - (c.z - a.z) * dx) / denominator
                if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
                    cuts.append(max(0, min(1, t)))
        cuts = sorted(set(cuts))
        if any(
            not _inside(
                SpatialPoint(x=a.x + dx * (lo + hi) / 2, z=a.z + dz * (lo + hi) / 2),
                polygon,
            )
            for lo, hi in zip(cuts, cuts[1:])
        ):
            return False
    return True


def _wall_footprint(wall, start, end):
    length = hypot(wall.end.x - wall.start.x, wall.end.z - wall.start.z)
    dx = (wall.end.x - wall.start.x) / length
    dz = (wall.end.z - wall.start.z) / length
    return [
        SpatialPoint(wall.start.x + dx * t - dz * n, wall.start.z + dz * t + dx * n)
        for t, n in [
            (start, -wall.thickness / 2),
            (end, -wall.thickness / 2),
            (end, wall.thickness / 2),
            (start, wall.thickness / 2),
        ]
    ]


def _wall_solids(wall, openings):
    """按洞口的高度切片，仅返回墙的实体部分，不假定门扇开启方向。"""
    length = hypot(wall.end.x - wall.start.x, wall.end.z - wall.start.z)
    heights = sorted(
        {0.0, wall.height}
        | {
            y
            for opening in openings
            for y in (opening.sill_height, opening.sill_height + opening.height)
        }
    )
    for low, high in zip(heights, heights[1:]):
        middle = (low + high) / 2
        holes = sorted(
            (o.offset, o.offset + o.width)
            for o in openings
            if o.sill_height < middle < o.sill_height + o.height
        )
        cursor = 0.0
        for start, end in holes + [(length, length)]:
            if start - cursor > EPS:
                yield low, high, _wall_footprint(wall, cursor, start)
            cursor = max(cursor, end)


def validate_design(document: HomeDesignDocument, space: SpatialDocument):
    from app.services.home_installation_validation import (
        validate_references,
        installation_issues,
    )

    rooms = {r.id: r for r in space.rooms}
    walls = {w.id: w for w in space.walls}
    for surface in document.surfaces:
        if surface.room_id not in rooms:
            raise ValueError("饰面引用的房间不存在")
        if surface.wall_id is not None and (
            surface.wall_id not in walls
            or surface.room_id not in walls[surface.wall_id].room_ids
        ):
            raise ValueError("饰面引用的墙体不属于该房间")
    if any(item.room_id not in rooms for item in document.objects):
        raise ValueError("物件引用的房间不存在")
    validate_references(document, rooms, walls)
    issues = list(
        islice(
            chain(
                _geometry_issues(document, space, rooms, walls),
                installation_issues(document, space, rooms, walls),
            ),
            MAX_ISSUES + 1,
        )
    )
    if len(issues) > MAX_ISSUES:
        issues[-1] = DesignIssue(
            code="validation_issue_limit",
            message="问题较多，仅展示前 200 条；尚未完成全部风险检查，请修正后重新校验",
        )
    return DesignValidation(valid=not issues, issues=issues)


def _geometry_issues(document, space, rooms, walls):
    if space.scale_status != "confirmed":
        yield DesignIssue(code="scale_unconfirmed", message="绑定空间的尺度尚未确认")
    boxes = {item.id: footprint(item) for item in document.objects}
    for item in document.objects:
        room = rooms[item.room_id]
        if not _contained(boxes[item.id], room.polygon):
            yield DesignIssue(
                code="object_outside_room",
                message=f"{item.name} 超出房间边界",
                object_ids=[item.id],
            )
        if item.position.y + item.size.height > room.height + EPS:
            yield DesignIssue(
                code="object_above_ceiling",
                message=f"{item.name} 超过房间净高",
                object_ids=[item.id],
            )
    for a, b in combinations(document.objects, 2):
        if min(a.position.y + a.size.height, b.position.y + b.size.height) - max(
            a.position.y, b.position.y
        ) > EPS and _interiors_overlap(boxes[a.id], boxes[b.id]):
            yield DesignIssue(
                code="object_collision",
                message=f"{a.name} 与 {b.name} 体积重叠",
                object_ids=[a.id, b.id],
            )
    for wall in space.walls:
        solids = list(
            _wall_solids(wall, [o for o in space.openings if o.wall_id == wall.id])
        )
        for item in document.objects:
            if any(
                min(item.position.y + item.size.height, high)
                - max(item.position.y, low)
                > EPS
                and _interiors_overlap(boxes[item.id], solid)
                for low, high, solid in solids
            ):
                yield DesignIssue(
                    code="object_wall_collision",
                    message=f"{item.name} 与墙体 {wall.id} 实体重叠",
                    object_ids=[item.id],
                )
    for opening in space.openings:
        wall = walls[opening.wall_id]
        length = hypot(wall.end.x - wall.start.x, wall.end.z - wall.start.z)
        dx, dz = (
            (wall.end.x - wall.start.x) / length,
            (wall.end.z - wall.start.z) / length,
        )
        box = [
            SpatialPoint(
                x=wall.start.x + dx * t - dz * n, z=wall.start.z + dz * t + dx * n
            )
            for t, n in [
                (opening.offset, -wall.thickness / 2),
                (opening.offset + opening.width, -wall.thickness / 2),
                (opening.offset + opening.width, wall.thickness / 2),
                (opening.offset, wall.thickness / 2),
            ]
        ]
        for item in document.objects:
            if min(
                item.position.y + item.size.height, opening.sill_height + opening.height
            ) - max(item.position.y, opening.sill_height) > EPS and _interiors_overlap(
                boxes[item.id], box
            ):
                yield DesignIssue(
                    code="opening_obstructed",
                    message=f"{item.name} 占用门窗洞口",
                    object_ids=[item.id],
                    opening_id=opening.id,
                )
