"""任务级整屋事实；坐标始终为统一米制，不从识别图猜测比例。"""

from itertools import combinations
from math import hypot
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.scenes import RoomGeometry


EPSILON = 1e-9


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SpatialPoint(SpatialModel):
    x: float = Field(ge=-10000, le=10000)
    z: float = Field(ge=-10000, le=10000)


def _cross(a, b, c):
    return (b.x - a.x) * (c.z - a.z) - (b.z - a.z) * (c.x - a.x)


def _opposite(first, second):
    return (first > EPSILON and second < -EPSILON) or (
        second > EPSILON and first < -EPSILON
    )


def _edges(polygon):
    return list(zip(polygon, polygon[1:] + polygon[:1]))


def _proper_crossing(a, b, c, d):
    return _opposite(_cross(a, b, c), _cross(a, b, d)) and _opposite(
        _cross(c, d, a), _cross(c, d, b)
    )


def _intervals(polygon, x):
    intersections = sorted(
        a.z + (x - a.x) * (b.z - a.z) / (b.x - a.x)
        for a, b in _edges(polygon)
        if min(a.x, b.x) < x < max(a.x, b.x)
    )
    return list(zip(intersections[::2], intersections[1::2]))


def _interiors_overlap(first, second):
    if (
        min(p.x for p in first) >= max(p.x for p in second)
        or min(p.x for p in second) >= max(p.x for p in first)
        or min(p.z for p in first) >= max(p.z for p in second)
        or min(p.z for p in second) >= max(p.z for p in first)
    ):
        return False
    # 真正穿越边界必产生内部交集。其余情况中，顶点横坐标划分出的条带内拓扑不变；
    # 偶奇扫描线支持任意简单凹多边形，且不会把共边、共点误判为面积重叠。
    for a, b in _edges(first):
        for c, d in _edges(second):
            if _proper_crossing(a, b, c, d):
                return True
    xs = sorted({p.x for p in first + second})
    for left, right in zip(xs, xs[1:]):
        x = (left + right) / 2
        for low_a, high_a in _intervals(first, x):
            for low_b, high_b in _intervals(second, x):
                if min(high_a, high_b) - max(low_a, low_b) > EPSILON:
                    return True
    return False


def _boundary_covers(start, end, polygon):
    dx, dz = end.x - start.x, end.z - start.z
    length_squared = dx * dx + dz * dz
    intervals = []
    for a, b in _edges(polygon):
        if abs(_cross(start, end, a)) > EPSILON or abs(_cross(start, end, b)) > EPSILON:
            continue
        values = [
            ((p.x - start.x) * dx + (p.z - start.z) * dz) / length_squared
            for p in (a, b)
        ]
        intervals.append((max(0, min(values)), min(1, max(values))))
    covered = 0.0
    for low, high in sorted(intervals):
        if low > covered + EPSILON:
            return False
        covered = max(covered, high)
    return covered >= 1 - EPSILON


class SpatialRoom(SpatialModel):
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    polygon: list[SpatialPoint] = Field(min_length=3, max_length=100)
    height: float = Field(gt=1.8, le=8)

    @model_validator(mode="after")
    def validate_polygon(self):
        RoomGeometry(
            id=self.id,
            name=self.name,
            floor_polygon=[p.model_dump() for p in self.polygon],
            ceiling_height=self.height,
        )
        # 旧场景校验的叉积乘积容差会遗漏毫米级交叉，整屋单独比较方向符号。
        for (a, b), (c, d) in combinations(_edges(self.polygon), 2):
            if _proper_crossing(a, b, c, d):
                raise ValueError("房间边界不能自交")
        for index, a in enumerate(self.polygon):
            b = self.polygon[(index + 1) % len(self.polygon)]
            c = self.polygon[(index + 2) % len(self.polygon)]
            if hypot(b.x - a.x, b.z - a.z) < 1e-6:
                raise ValueError("房间存在零长度边")
            if (
                abs(_cross(a, b, c)) <= EPSILON
                and (b.x - a.x) * (c.x - b.x) + (b.z - a.z) * (c.z - b.z) < 0
            ):
                raise ValueError("相邻房间边不能回折重叠")
        return self


class SpatialWall(SpatialModel):
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    start: SpatialPoint
    end: SpatialPoint
    room_ids: list[str] = Field(min_length=1, max_length=2)
    height: float = Field(gt=0, le=8)
    thickness: float = Field(gt=0, le=1)


class SpatialOpening(SpatialModel):
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    wall_id: str = Field(min_length=1, max_length=100)
    type: Literal["door", "window", "passage"]
    offset: float = Field(ge=0, le=10000)
    width: float = Field(gt=0, le=20)
    height: float = Field(gt=0, le=8)
    sill_height: float = Field(default=0, ge=0, le=8)


class SpatialDocument(SpatialModel):
    schema_version: Literal["spatial/1.0"]
    unit: Literal["m"]
    scale_status: Literal["unconfirmed", "confirmed"]
    source_image_id: int | None = Field(default=None, gt=0)
    rooms: list[SpatialRoom] = Field(min_length=1, max_length=50)
    walls: list[SpatialWall] = Field(default_factory=list, max_length=500)
    openings: list[SpatialOpening] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_topology(self):
        for kind, items in (
            ("房间", self.rooms),
            ("墙体", self.walls),
            ("开口", self.openings),
        ):
            if len({item.id for item in items}) != len(items):
                raise ValueError(f"{kind} ID 不能重复")
        rooms = {room.id: room for room in self.rooms}
        walls = {wall.id: wall for wall in self.walls}
        for first, second in combinations(self.rooms, 2):
            if _interiors_overlap(first.polygon, second.polygon):
                raise ValueError(f"房间内部不能重叠：{first.id} / {second.id}")
        for wall in self.walls:
            if hypot(wall.end.x - wall.start.x, wall.end.z - wall.start.z) < 1e-6:
                raise ValueError("墙体不能为零长度")
            if len(set(wall.room_ids)) != len(wall.room_ids):
                raise ValueError("墙体房间引用不能重复")
            for room_id in wall.room_ids:
                if room_id not in rooms:
                    raise ValueError("墙体引用的房间不存在")
                room = rooms[room_id]
                if wall.height > room.height + EPSILON or not _boundary_covers(
                    wall.start, wall.end, room.polygon
                ):
                    raise ValueError("墙体必须位于引用房间的边界且不高于房间")
        for first, second in combinations(self.walls, 2):
            if (
                abs(_cross(first.start, first.end, second.start)) <= EPSILON
                and abs(_cross(first.start, first.end, second.end)) <= EPSILON
            ):
                dx, dz = first.end.x - first.start.x, first.end.z - first.start.z
                length_squared = dx * dx + dz * dz
                values = [
                    ((p.x - first.start.x) * dx + (p.z - first.start.z) * dz)
                    / length_squared
                    for p in (second.start, second.end)
                ]
                if min(1, max(values)) - max(0, min(values)) > EPSILON:
                    raise ValueError("同一段墙体必须使用一个稳定 ID 和共享房间引用")
        for opening in self.openings:
            wall = walls.get(opening.wall_id)
            if wall is None:
                raise ValueError("开口引用的墙体不存在")
            if (
                opening.offset + opening.width
                > hypot(wall.end.x - wall.start.x, wall.end.z - wall.start.z) + EPSILON
                or opening.sill_height + opening.height > wall.height + EPSILON
            ):
                raise ValueError("开口超出墙体范围")
        for first, second in combinations(self.openings, 2):
            if (
                first.wall_id == second.wall_id
                and min(first.offset + first.width, second.offset + second.width)
                - max(first.offset, second.offset)
                > EPSILON
                and min(
                    first.sill_height + first.height, second.sill_height + second.height
                )
                - max(first.sill_height, second.sill_height)
                > EPSILON
            ):
                raise ValueError("同一墙体的开口不能重叠")
        return self


class SpatialSaveRequest(SpatialModel):
    base_version: int = Field(ge=0)
    client_mutation_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    document: SpatialDocument


class SpatialResponse(SpatialModel):
    task_id: int
    version: int = Field(ge=0)
    document: SpatialDocument | None
