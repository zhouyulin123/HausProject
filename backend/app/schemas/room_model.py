"""RoomModel：VL 空间识别产出的统一空间事实模型。

RoomModel 是「感知层」中间态：VL 输出 + 用户校准后的结构化空间事实，
独立于「生成层」的 SceneDocument（可编辑、可渲染的 3D 场景）。
`room_model_service.room_model_to_scene` 负责从前者生成后者。

坐标约定：平面用 x/z（与 SceneDocument 一致，Y 轴向上），
RoomModel 内一律使用归一化坐标（0~1），真实米制由 scale 与用户校准换算。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class RoomModelBase(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class RoomPoint(RoomModelBase):
    """归一化顶点（0~1），平面 x/z。"""

    x: float = Field(ge=0, le=1)
    z: float = Field(ge=0, le=1)


class RoomPolygon(RoomModelBase):
    """一个房间的归一化地板多边形；边即墙体。"""

    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    floor_polygon: list[RoomPoint] = Field(min_length=3, max_length=100)
    ceiling_height: float | None = Field(default=None, ge=1.8, le=8)
    # 用户校准后的真实宽/深（米）；缺省时由 room_model_to_scene 按默认尺寸兜底
    width_m: float | None = Field(default=None, gt=0, le=50)
    depth_m: float | None = Field(default=None, gt=0, le=50)
    confidence: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def validate_polygon(self) -> "RoomPolygon":
        points = [(point.x, point.z) for point in self.floor_polygon]
        if len(set(points)) < 3:
            raise ValueError("floorPolygon 至少需要 3 个不同顶点")
        return self


class RoomOpening(RoomModelBase):
    """挂在某房间某面墙上的门/窗/洞口（归一化位置）。"""

    id: str = Field(min_length=1, max_length=100)
    room_id: str = Field(min_length=1, max_length=100)
    type: Literal["door", "window", "passage"]
    wall_index: int = Field(ge=0)
    offset: float = Field(ge=0, le=1)  # 沿墙起点的比例 0~1
    width: float = Field(gt=0, le=1)  # 占墙长比例 0~1
    height: float | None = Field(default=None, ge=0, le=8)  # 米，可空待校准
    sill_height: float = Field(default=0, ge=0, le=8)
    confidence: float = Field(default=0.6, ge=0, le=1)


class RoomWall(RoomModelBase):
    """墙的补充属性（多边形边之外的语义，如承重）。"""

    room_id: str = Field(min_length=1, max_length=100)
    wall_index: int = Field(ge=0)
    load_bearing: bool | None = None  # None = 未知
    confidence: float = Field(default=0.6, ge=0, le=1)


class ExistingFurniture(RoomModelBase):
    """识别到的既有家具（文字级，不做精确坐标）。"""

    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    room_id: str = Field(min_length=1, max_length=100)
    confidence: float = Field(default=0.5, ge=0, le=1)


class FixedObstacle(RoomModelBase):
    """承重柱、烟道等不可移动区域。"""

    name: str = Field(min_length=1, max_length=100)
    room_id: str = Field(min_length=1, max_length=100)
    confidence: float = Field(default=0.5, ge=0, le=1)


class RoomScale(RoomModelBase):
    """归一化坐标 → 真实米的参考尺度。

    VL 对绝对尺寸不可靠，因此真实尺寸优先由用户校准给出；
    缺省时按房间类型默认尺寸兜底，并在 confidence 上体现。
    """

    source: Literal["vl", "user", "default"] = "default"
    reference_wall_length: float | None = Field(default=None, gt=0, le=50)
    reference_room_id: str | None = Field(default=None, max_length=100)
    reference_wall_index: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)


class RoomModel(RoomModelBase):
    """统一空间事实模型：方案 Agent 上下文 + Scene Agent 约束 + 3D 初始化来源。"""

    schema_version: Literal["1.0"] = "1.0"
    # 识别元信息：图片类型 + 主要空间 + 户型文字描述（如"三室两厅"）
    image_kind: Literal["floor_plan", "room_photo", "other"] | None = None
    space_type: str | None = Field(default=None, max_length=50)
    room_count: str | None = Field(default=None, max_length=100)
    rooms: list[RoomPolygon] = Field(min_length=1, max_length=50)
    walls: list[RoomWall] = Field(default_factory=list, max_length=200)
    doors: list[RoomOpening] = Field(default_factory=list, max_length=100)
    windows: list[RoomOpening] = Field(default_factory=list, max_length=100)
    fixed_obstacles: list[FixedObstacle] = Field(
        default_factory=list, max_length=50
    )
    existing_furniture: list[ExistingFurniture] = Field(
        default_factory=list, max_length=100
    )
    scale: RoomScale = Field(default_factory=RoomScale)
    confidence: float = Field(default=0.5, ge=0, le=1)
    requires_confirmation: list[str] = Field(default_factory=list)
    # 保留原 VL 的文字级观察与建议，供方案生成与前端展示使用
    analysis_notes: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "RoomModel":
        rooms_by_id = {room.id: room for room in self.rooms}
        for opening in [*self.doors, *self.windows]:
            room = rooms_by_id.get(opening.room_id)
            if room is None:
                raise ValueError(
                    f"opening 引用了不存在的房间: {opening.room_id}"
                )
            if opening.wall_index >= len(room.floor_polygon):
                raise ValueError(
                    f"opening.wallIndex 超出房间墙体范围: {opening.id}"
                )
        for wall in self.walls:
            room = rooms_by_id.get(wall.room_id)
            if room is None:
                raise ValueError(f"wall 引用了不存在的房间: {wall.room_id}")
            if wall.wall_index >= len(room.floor_polygon):
                raise ValueError(f"wall.wallIndex 超出房间墙体范围: {wall.room_id}")
        for furniture in self.existing_furniture:
            if furniture.room_id not in rooms_by_id:
                raise ValueError(
                    f"existingFurniture 引用了不存在的房间: {furniture.room_id}"
                )
        for obstacle in self.fixed_obstacles:
            if obstacle.room_id not in rooms_by_id:
                raise ValueError(
                    f"fixedObstacle 引用了不存在的房间: {obstacle.room_id}"
                )
        return self


class RoomModelCalibrationRequest(RoomModelBase):
    """用户对主空间真实尺寸的校准请求。"""

    room_id: str | None = Field(default=None, max_length=100)
    width_m: float = Field(gt=0, le=50)
    depth_m: float = Field(gt=0, le=50)
    ceiling_height_m: float | None = Field(default=None, ge=1.8, le=8)
