"""显式安装与使用要求的几何检查，不代表专业安全认证。"""

from math import cos, sin, radians, hypot, dist

from app.schemas.home_design import DesignIssue
from app.schemas.spatial import _interiors_overlap
from app.services.home_design_validation import (
    EPS,
    SpatialPoint,
    footprint,
    _inside,
    _contained,
    _wall_solids,
)


def validate_references(document, rooms, walls):
    points = {point.id: point for point in document.points}
    if any(point.room_id not in rooms for point in document.points):
        raise ValueError("点位引用的房间不存在")
    for item in document.objects:
        installation = item.installation
        if (
            installation
            and installation.kind == "wall"
            and (
                installation.wall_id not in walls
                or item.room_id not in walls[installation.wall_id].room_ids
            )
        ):
            raise ValueError("安装宿主墙不存在或不属于物件房间")
        requirement = item.point_requirement
        if requirement and (
            requirement.point_id not in points
            or points[requirement.point_id].room_id != item.room_id
        ):
            raise ValueError("关联点位不存在或不属于物件房间")


def _issue(code, message, item=None, other=None):
    return DesignIssue(
        code=code, message=message, object_ids=[i.id for i in (item, other) if i]
    )


def _wall_contact(item, wall, room, openings):
    angle = radians(item.rotation)
    c, s = cos(angle), sin(angle)
    dx, dz = wall.end.x - wall.start.x, wall.end.z - wall.start.z
    length = hypot(dx, dz)
    dx, dz = dx / length, dz / length
    # 本地 +Z 为正面，背面中心沿 -Z；背面整条边必须与墙实体面贴合。
    x = item.position.x - s * item.size.depth / 2
    z = item.position.z - c * item.size.depth / 2
    along = (x - wall.start.x) * dx + (z - wall.start.z) * dz
    normal = -(x - wall.start.x) * dz + (z - wall.start.z) * dx
    if abs(c * dz + s * dx) > EPS or abs(abs(normal) - wall.thickness / 2) > EPS:
        return False
    if along - item.size.width / 2 < -EPS or along + item.size.width / 2 > length + EPS:
        return False
    if item.position.y + item.size.height > wall.height + EPS:
        return False
    if not _inside(SpatialPoint(x + s * 0.001, z + c * 0.001), room.polygon):
        return False
    # 正面必须离开墙实体，而不是从另一面朝墙内穿入。
    if normal * (-s * dz + c * dx) <= 0:
        return False
    return not any(
        min(along + item.size.width / 2, o.offset + o.width)
        - max(along - item.size.width / 2, o.offset)
        > EPS
        and min(item.position.y + item.size.height, o.sill_height + o.height)
        - max(item.position.y, o.sill_height)
        > EPS
        for o in openings
        if o.wall_id == wall.id
    )


def _clearance_box(item):
    clearance = item.clearance
    angle = radians(item.rotation)
    c, s = cos(angle), sin(angle)
    left = -item.size.width / 2 - clearance.left
    right = item.size.width / 2 + clearance.right
    back = -item.size.depth / 2 - clearance.back
    front = item.size.depth / 2 + clearance.front
    return [
        SpatialPoint(item.position.x + x * c + z * s, item.position.z - x * s + z * c)
        for x, z in ((left, back), (right, back), (right, front), (left, front))
    ]


def installation_issues(document, space, rooms, walls):
    points = {point.id: point for point in document.points}
    boxes = {item.id: footprint(item) for item in document.objects}
    for point in document.points:
        if not point.confirmed:
            yield _issue("point_unconfirmed", f"点位 {point.name} 尚待现场确认")
        if not _inside(point.position, rooms[point.room_id].polygon):
            yield _issue("point_outside_room", f"点位 {point.name} 超出房间边界")
        if point.position.y > rooms[point.room_id].height + EPS:
            yield _issue("point_above_ceiling", f"点位 {point.name} 超过房间净高")
    for item in document.objects:
        room = rooms[item.room_id]
        installation = item.installation
        if installation:
            if installation.kind == "floor" and abs(item.position.y) > EPS:
                yield _issue("installation_floor_gap", "落地物件底面未贴地", item)
            elif (
                installation.kind == "ceiling"
                and abs(item.position.y + item.size.height - room.height) > EPS
            ):
                yield _issue("installation_ceiling_gap", "吊装物件顶部未贴合顶面", item)
            elif installation.kind == "wall" and not _wall_contact(
                item, walls[installation.wall_id], room, space.openings
            ):
                yield _issue(
                    "installation_wall_contact",
                    "墙装物件背面未完整贴合宿主墙实体面",
                    item,
                )
        requirement = item.point_requirement
        if requirement:
            point = points[requirement.point_id]
            if (
                dist(
                    (item.position.x, item.position.y, item.position.z),
                    (point.position.x, point.position.y, point.position.z),
                )
                > requirement.max_distance_m + EPS
            ):
                yield _issue(
                    "point_distance_exceeded",
                    "物件与关联点位的三维距离超过指定范围",
                    item,
                )
        clearance = item.clearance
        if clearance is None:
            continue
        if not clearance.confirmed:
            yield _issue("clearance_unconfirmed", "物件使用预留要求尚未确认", item)
        box = _clearance_box(item)
        top = item.position.y + item.size.height + clearance.above
        if not _contained(box, room.polygon):
            yield _issue("clearance_outside_room", "使用预留区超出房间边界", item)
        if top > room.height + EPS:
            yield _issue("clearance_above_ceiling", "上方使用预留区超过房间净高", item)
        for other in document.objects:
            if (
                other.id != item.id
                and min(top, other.position.y + other.size.height)
                - max(item.position.y, other.position.y)
                > EPS
                and _interiors_overlap(box, boxes[other.id])
            ):
                yield _issue(
                    "clearance_object_collision",
                    "使用预留区被其他物件占用",
                    item,
                    other,
                )
        for wall in space.walls:
            if any(
                min(top, high) - max(item.position.y, low) > EPS
                and _interiors_overlap(box, solid)
                for low, high, solid in _wall_solids(
                    wall, [o for o in space.openings if o.wall_id == wall.id]
                )
            ):
                yield _issue(
                    "clearance_wall_collision", "使用预留区被墙体实体占用", item
                )
