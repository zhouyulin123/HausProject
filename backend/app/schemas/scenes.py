"""Web 3D 场景的版本化数据契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    epsilon = 1e-9

    def orientation(
        start: tuple[float, float],
        end: tuple[float, float],
        point: tuple[float, float],
    ) -> float:
        return (
            (end[0] - start[0]) * (point[1] - start[1])
            - (end[1] - start[1]) * (point[0] - start[0])
        )

    def on_segment(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - epsilon
            <= point[0]
            <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    first_side_a = orientation(first_start, first_end, second_start)
    first_side_b = orientation(first_start, first_end, second_end)
    second_side_a = orientation(second_start, second_end, first_start)
    second_side_b = orientation(second_start, second_end, first_end)
    if (
        first_side_a * first_side_b < -epsilon
        and second_side_a * second_side_b < -epsilon
    ):
        return True
    return any(
        (
            abs(value) <= epsilon and on_segment(point, start, end)
            for value, point, start, end in (
                (first_side_a, second_start, first_start, first_end),
                (first_side_b, second_end, first_start, first_end),
                (second_side_a, first_start, second_start, second_end),
                (second_side_b, first_end, second_start, second_end),
            )
        )
    )


class SceneModel(BaseModel):
    """场景文档内部统一使用 snake_case，对外序列化为 camelCase。"""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class Vector2XZ(SceneModel):
    x: float
    z: float


class Vector3(SceneModel):
    x: float
    y: float
    z: float


class PositiveVector3(SceneModel):
    x: float = Field(gt=0, le=100)
    y: float = Field(gt=0, le=100)
    z: float = Field(gt=0, le=100)


class Transform(SceneModel):
    position: Vector3
    rotation: Vector3 = Field(
        default_factory=lambda: Vector3(x=0, y=0, z=0)
    )
    scale: PositiveVector3 = Field(
        default_factory=lambda: PositiveVector3(x=1, y=1, z=1)
    )


class RoomGeometry(SceneModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    floor_polygon: list[Vector2XZ] = Field(min_length=3, max_length=100)
    ceiling_height: float = Field(gt=1.8, le=8)
    wall_thickness: float = Field(default=0.12, gt=0, le=1)

    @model_validator(mode="after")
    def validate_floor_polygon(self) -> "RoomGeometry":
        points = [(point.x, point.z) for point in self.floor_polygon]
        if len(set(points)) < 3:
            raise ValueError("floorPolygon 至少需要 3 个不同顶点")

        segments = list(zip(points, points[1:] + points[:1]))
        segment_count = len(segments)
        for first_index, first_segment in enumerate(segments):
            for second_index in range(first_index + 1, segment_count):
                are_adjacent = (
                    second_index == first_index + 1
                    or (first_index == 0 and second_index == segment_count - 1)
                )
                if are_adjacent:
                    continue
                if _segments_intersect(
                    *first_segment,
                    *segments[second_index],
                ):
                    raise ValueError("floorPolygon 的非相邻边不能相交")

        doubled_area = sum(
            x1 * z2 - x2 * z1
            for (x1, z1), (x2, z2) in zip(
                points,
                points[1:] + points[:1],
            )
        )
        if abs(doubled_area) < 1e-6:
            raise ValueError("floorPolygon 必须围成有效面积")
        return self


class Opening(SceneModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal["door", "window", "passage"]
    wall_index: int = Field(ge=0)
    offset: float = Field(ge=0)
    width: float = Field(gt=0, le=20)
    height: float = Field(gt=0, le=8)
    sill_height: float = Field(default=0, ge=0, le=8)

    @model_validator(mode="after")
    def validate_vertical_extent(self) -> "Opening":
        if self.sill_height + self.height > 8:
            raise ValueError("洞口顶部高度不能超过 8 米")
        return self


class MaterialOverride(SceneModel):
    slot: str = Field(min_length=1, max_length=100)
    material_id: str | None = Field(default=None, max_length=100)
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
    )


class SceneItem(SceneModel):
    instance_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    sku: str = Field(min_length=1, max_length=50)
    category: str | None = Field(default=None, max_length=50)
    transform: Transform
    dimensions: PositiveVector3 | None = None
    materials: list[MaterialOverride] = Field(
        default_factory=list,
        max_length=30,
    )


class SceneCamera(SceneModel):
    position: Vector3
    target: Vector3
    fov: float = Field(default=50, gt=10, lt=120)


class SceneDocument(SceneModel):
    """可以被 Web 编辑器、Scene Agent 与 Blender 共同消费的场景快照。"""

    schema_version: Literal["1.0"] = "1.0"
    unit: Literal["m"] = "m"
    coordinate_system: Literal["right-handed-y-up"] = "right-handed-y-up"
    room: RoomGeometry
    openings: list[Opening] = Field(default_factory=list, max_length=100)
    items: list[SceneItem] = Field(default_factory=list, max_length=500)
    camera: SceneCamera | None = None

    @model_validator(mode="after")
    def validate_scene_references(self) -> "SceneDocument":
        item_ids = [item.instance_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("items 中的 instanceId 不能重复")

        opening_ids = [opening.id for opening in self.openings]
        if len(opening_ids) != len(set(opening_ids)):
            raise ValueError("openings 中的 id 不能重复")

        wall_count = len(self.room.floor_polygon)
        invalid_wall_indexes = sorted(
            {
                opening.wall_index
                for opening in self.openings
                if opening.wall_index >= wall_count
            }
        )
        if invalid_wall_indexes:
            raise ValueError(
                "opening.wallIndex 超出墙体范围: "
                + ", ".join(str(index) for index in invalid_wall_indexes)
            )
        return self


class SceneValidationIssue(BaseModel):
    code: str
    message: str
    path: str | None = None


class SceneValidationReport(BaseModel):
    valid: bool
    errors: list[SceneValidationIssue] = Field(default_factory=list)
    warnings: list[SceneValidationIssue] = Field(default_factory=list)


SceneSource = Literal[
    "manual",
    "scene_agent",
    "import",
    "migration",
    "auto_layout",
]


class SceneCreateRequest(BaseModel):
    scene: SceneDocument
    source: SceneSource = "manual"


class SceneUpdateRequest(BaseModel):
    base_version: int = Field(ge=1)
    scene: SceneDocument
    source: SceneSource = "manual"


class SceneResponse(BaseModel):
    id: int
    plan_version_id: int
    current_version: int
    scene: SceneDocument
    validation: SceneValidationReport
    source: SceneSource
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SceneVersionResponse(BaseModel):
    version: int
    scene: SceneDocument
    validation: SceneValidationReport
    source: SceneSource
    created_at: datetime | None = None


class SceneVersionListResponse(BaseModel):
    versions: list[SceneVersionResponse]
