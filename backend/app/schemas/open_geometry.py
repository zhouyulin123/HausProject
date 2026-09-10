"""受控开放几何家具 DSL 及 API 契约。"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.open_geometry_contract import contract_limit, open_geometry_contract


MAX_COORDINATE = contract_limit("max_coordinate_mm")
MAX_SEGMENTS = contract_limit("max_segments")
MAX_CONTROL_POINTS = contract_limit("max_control_points")
SCHEMA_VERSION = open_geometry_contract()["schema_version"]
MIN_GEOMETRY_LENGTH_MM = contract_limit("min_geometry_length_mm")
Vector3 = Annotated[list[float], Field(min_length=3, max_length=3)]
ProfilePoint = Annotated[list[float], Field(min_length=2, max_length=2)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class OpenGeometryMaterial(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    base_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    roughness: float = Field(ge=0, le=1)
    metallic: float = Field(ge=0, le=1)


class BoxGeometry(StrictModel):
    type: Literal["box"]
    size_mm: Vector3
    radius_mm: float = Field(default=0, ge=0, le=500)

    @model_validator(mode="after")
    def validate_size(self) -> "BoxGeometry":
        if any(value < 1 or value > 6000 for value in self.size_mm):
            raise ValueError("box 尺寸必须在 1..6000mm")
        if self.radius_mm > min(self.size_mm) / 2:
            raise ValueError("box 圆角不能超过最小尺寸的一半")
        return self


class CylinderGeometry(StrictModel):
    type: Literal["cylinder"]
    radius_mm: float = Field(gt=0, le=3000)
    top_radius_mm: float | None = Field(default=None, gt=0, le=3000)
    height_mm: float = Field(gt=0, le=6000)
    radial_segments: int = Field(default=32, ge=8, le=MAX_SEGMENTS)


class SphereGeometry(StrictModel):
    type: Literal["sphere"]
    radius_mm: float = Field(gt=0, le=3000)
    scale: Vector3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    segments: int = Field(default=32, ge=8, le=MAX_SEGMENTS)

    @model_validator(mode="after")
    def validate_scale(self) -> "SphereGeometry":
        if any(value <= 0 or value > 8 for value in self.scale):
            raise ValueError("sphere scale 必须在 (0, 8]")
        return self


class SweepGeometry(StrictModel):
    type: Literal["sweep"]
    path_mm: list[Vector3] = Field(min_length=3, max_length=MAX_CONTROL_POINTS)
    radius_mm: float = Field(gt=0, le=500)
    tubular_segments: int = Field(default=32, ge=8, le=MAX_SEGMENTS)
    radial_segments: int = Field(default=12, ge=6, le=32)
    closed: bool = False

    @model_validator(mode="after")
    def validate_path(self) -> "SweepGeometry":
        minimum_squared = MIN_GEOMETRY_LENGTH_MM**2
        segment_lengths_squared = [
            sum((right[index] - left[index]) ** 2 for index in range(3))
            for left, right in zip(self.path_mm, self.path_mm[1:])
        ]
        if sum(math.sqrt(length) for length in segment_lengths_squared) < MIN_GEOMETRY_LENGTH_MM:
            raise ValueError(
                f"sweep 路径总长度必须至少为 {MIN_GEOMETRY_LENGTH_MM}mm，"
                "请提供彼此分离的控制点"
            )
        if any(length < minimum_squared for length in segment_lengths_squared):
            raise ValueError(
                f"sweep 连续控制点间距必须至少为 {MIN_GEOMETRY_LENGTH_MM}mm，"
                "请删除重复点或拉开相邻控制点"
            )
        if self.closed:
            closing_length_squared = sum(
                (self.path_mm[-1][index] - self.path_mm[0][index]) ** 2
                for index in range(3)
            )
            if closing_length_squared < minimum_squared:
                raise ValueError(
                    f"sweep 闭合端点间距必须至少为 {MIN_GEOMETRY_LENGTH_MM}mm；"
                    "closed=true 时不要在末尾重复起点"
                )
        return self


class LatheGeometry(StrictModel):
    type: Literal["lathe"]
    profile_mm: list[ProfilePoint] = Field(min_length=3, max_length=MAX_CONTROL_POINTS)
    segments: int = Field(default=32, ge=8, le=MAX_SEGMENTS)

    @model_validator(mode="after")
    def validate_profile(self) -> "LatheGeometry":
        if any(point[0] < 0 for point in self.profile_mm):
            raise ValueError("lathe 轮廓半径不能为负数")
        if max(point[0] for point in self.profile_mm) < MIN_GEOMETRY_LENGTH_MM:
            raise ValueError(
                f"lathe 轮廓无法生成可见表面：至少一个半径必须达到 "
                f"{MIN_GEOMETRY_LENGTH_MM}mm"
            )
        minimum_squared = MIN_GEOMETRY_LENGTH_MM**2
        has_visible_segment = any(
            (left[0] + right[0] >= MIN_GEOMETRY_LENGTH_MM)
            and sum((right[index] - left[index]) ** 2 for index in range(2))
            >= minimum_squared
            for left, right in zip(self.profile_mm, self.profile_mm[1:])
        )
        if not has_visible_segment:
            raise ValueError(
                "lathe 轮廓无法生成可见表面：请提供长度至少为 0.1mm "
                "且离开旋转轴的轮廓线段"
            )
        return self


OpenGeometryShape = Annotated[
    BoxGeometry | CylinderGeometry | SphereGeometry | SweepGeometry | LatheGeometry,
    Field(discriminator="type"),
]


class OpenGeometryPart(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    material_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    parent_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    position_mm: Vector3
    rotation_deg: Vector3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    geometry: OpenGeometryShape

    @model_validator(mode="after")
    def validate_transform(self) -> "OpenGeometryPart":
        if any(abs(value) > MAX_COORDINATE for value in self.position_mm):
            raise ValueError("部件位置超出允许坐标范围")
        if any(value != 0 for value in self.rotation_deg):
            raise ValueError("开放几何 v1 暂不支持部件旋转，请用曲线路径表达方向")
        return self


class OpenGeometryDesign(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    scale: Vector3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    materials: list[OpenGeometryMaterial] = Field(min_length=1)
    parts: list[OpenGeometryPart] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph_and_complexity(self) -> "OpenGeometryDesign":
        limits = open_geometry_contract()["limits"]
        if any(value < 0.25 or value > 4 for value in self.scale):
            raise ValueError("设计级 scale 必须在 0.25..4")
        if len(self.parts) > limits["max_parts"]:
            raise ValueError("部件数量超过开放几何复杂度上限")
        if len(self.materials) > limits["max_materials"]:
            raise ValueError("材质数量超过开放几何复杂度上限")
        material_ids = [item.id for item in self.materials]
        part_ids = [item.id for item in self.parts]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("材质 ID 必须唯一")
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("部件 ID 必须唯一")
        known_parts = set(part_ids)
        known_materials = set(material_ids)
        parents: dict[str, str] = {}
        control_points = 0
        for part in self.parts:
            if part.material_id not in known_materials:
                raise ValueError(f"部件 {part.id} 引用了不存在的材质")
            if part.parent_id is not None:
                if part.parent_id not in known_parts:
                    raise ValueError(f"部件 {part.id} 引用了不存在的父部件")
                if part.parent_id == part.id:
                    raise ValueError("部件不能引用自身作为父部件")
                parents[part.id] = part.parent_id
            geometry = part.geometry
            if isinstance(geometry, SweepGeometry):
                control_points += len(geometry.path_mm)
                for point in geometry.path_mm:
                    if any(abs(value) > MAX_COORDINATE for value in point):
                        raise ValueError("sweep 控制点超出允许坐标范围")
            elif isinstance(geometry, LatheGeometry):
                control_points += len(geometry.profile_mm)
                for radius, height in geometry.profile_mm:
                    if radius > MAX_COORDINATE or abs(height) > MAX_COORDINATE:
                        raise ValueError("lathe 轮廓点超出允许坐标范围")
        if control_points > limits["max_total_control_points"]:
            raise ValueError("控制点总数超过开放几何复杂度上限")
        for part_id in parents:
            seen: set[str] = set()
            cursor = part_id
            while cursor in parents:
                if cursor in seen:
                    raise ValueError("部件父子关系存在循环引用")
                seen.add(cursor)
                cursor = parents[cursor]
        return self


class OpenGeometryPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    scale: Vector3 | None = None
    upsert_materials: list[OpenGeometryMaterial] = Field(default_factory=list)
    remove_material_ids: list[str] = Field(default_factory=list, max_length=12)
    upsert_parts: list[OpenGeometryPart] = Field(default_factory=list)
    remove_part_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_non_empty(self) -> "OpenGeometryPatch":
        if not any((self.name, self.description is not None, self.scale is not None, self.upsert_materials,
                    self.remove_material_ids, self.upsert_parts, self.remove_part_ids)):
            raise ValueError("patch 至少包含一项修改")
        return self


class OpenGeometryCreateOperation(StrictModel):
    operation: Literal["create"]
    design: OpenGeometryDesign


class OpenGeometryPatchOperation(StrictModel):
    operation: Literal["patch"]
    patch: OpenGeometryPatch


class OpenGeometryUnsupportedOperation(StrictModel):
    operation: Literal["unsupported"]
    reason: str = Field(min_length=1, max_length=500)


OpenGeometryOperation = Annotated[
    OpenGeometryCreateOperation | OpenGeometryPatchOperation | OpenGeometryUnsupportedOperation,
    Field(discriminator="operation"),
]


class OpenGeometryCommandRequest(StrictModel):
    client_mutation_id: str = Field(min_length=1, max_length=100)
    base_version: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=1000)


class OpenGeometryRestoreRequest(StrictModel):
    client_mutation_id: str = Field(min_length=1, max_length=100)
    base_version: int = Field(ge=1)
    target_version: int = Field(ge=1)


class OpenGeometryVersion(StrictModel):
    version: int
    source: Literal["llm", "restore"]
    instruction: str
    design: OpenGeometryDesign
    model_spec: dict[str, Any]


class OpenGeometryStateResponse(StrictModel):
    task_id: int
    current_version: int
    current: OpenGeometryVersion | None
    history: list[OpenGeometryVersion] = Field(default_factory=list)


class OpenGeometryCommandResponse(OpenGeometryStateResponse):
    reply: str
