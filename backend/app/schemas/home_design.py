"""整屋家装草稿契约，显式绑定空间的不可变版本。"""

from typing import Literal

from pydantic import Field, model_validator, model_serializer

from app.schemas.spatial import SpatialModel


class Material(SpatialModel):
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class DesignSurface(SpatialModel):
    quote_rule_id: int | None = Field(default=None, ge=1, strict=True)
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    room_id: str = Field(min_length=1, max_length=100)
    kind: Literal["floor", "ceiling", "wall"]
    wall_id: str | None = Field(default=None, min_length=1, max_length=100)
    material: Material

    @model_validator(mode="after")
    def wall_reference(self):
        if (self.kind == "wall") != (self.wall_id is not None):
            raise ValueError("墙面必须引用墙体，地面和顶面不能引用墙体")
        return self

    @model_serializer(mode="wrap")
    def serialize_optional_quote_rule(self, handler):
        value = handler(self)
        if self.quote_rule_id is None:
            value.pop("quote_rule_id", None)
        return value


class ObjectPosition(SpatialModel):
    x: float = Field(ge=-10000, le=10000)
    y: float = Field(ge=0, le=8)
    z: float = Field(ge=-10000, le=10000)


class ObjectSize(SpatialModel):
    width: float = Field(gt=0, le=100)
    height: float = Field(gt=0, le=8)
    depth: float = Field(gt=0, le=100)


class Installation(SpatialModel):
    kind: Literal["floor", "wall", "ceiling"]
    wall_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def wall_reference(self):
        if (self.kind == "wall") != (self.wall_id is not None):
            raise ValueError("墙装必须指定墙体，其他安装方式不能指定墙体")
        return self


class Clearance(SpatialModel):
    front: float = Field(ge=0, le=10)
    back: float = Field(ge=0, le=10)
    left: float = Field(ge=0, le=10)
    right: float = Field(ge=0, le=10)
    above: float = Field(ge=0, le=10)
    confirmed: bool = Field(strict=True)


class PointRequirement(SpatialModel):
    point_id: str = Field(min_length=1, max_length=100)
    max_distance_m: float = Field(ge=0, le=100)


class DesignPoint(SpatialModel):
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    room_id: str = Field(min_length=1, max_length=100)
    kind: Literal["socket", "switch", "water", "drain", "network", "other"]
    position: ObjectPosition
    confirmed: bool = Field(strict=True)


class DesignObject(SpatialModel):
    installation: Installation | None = None
    clearance: Clearance | None = None
    point_requirement: PointRequirement | None = None
    asset_id: int | None = Field(default=None, ge=1, strict=True)
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    room_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    category: Literal["furniture", "equipment", "lighting", "textile", "fixture"]
    position: ObjectPosition
    size: ObjectSize
    rotation: float = Field(ge=-360, le=360)
    material: Material

    @model_serializer(mode="wrap")
    def serialize_optional_asset(self, handler):
        value = handler(self)
        for field in ("asset_id", "installation", "clearance", "point_requirement"):
            if getattr(self, field) is None:
                value.pop(field, None)
        return value


class HomeDesignDocument(SpatialModel):
    points: list[DesignPoint] = Field(default_factory=list, max_length=200)
    schema_version: Literal["home-design/1.0"]
    space_version: int = Field(ge=1)
    surfaces: list[DesignSurface] = Field(default_factory=list, max_length=500)
    objects: list[DesignObject] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.surfaces, self.objects, self.points):
            if len({item.id for item in values}) != len(values):
                raise ValueError("对象标识不能重复")
        targets = [(s.room_id, s.kind, s.wall_id) for s in self.surfaces]
        if len(set(targets)) != len(targets):
            raise ValueError("同一表面只能指定一种饰面")
        return self

    @model_serializer(mode="wrap")
    def serialize_optional_points(self, handler):
        value = handler(self)
        if not self.points and "points" not in self.model_fields_set:
            value.pop("points", None)
        return value


class HomeDesignSaveRequest(SpatialModel):
    base_version: int = Field(ge=0)
    client_mutation_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    document: HomeDesignDocument


class DesignIssue(SpatialModel):
    code: str
    message: str
    object_ids: list[str] = Field(default_factory=list)
    opening_id: str | None = None


class DesignValidation(SpatialModel):
    valid: bool
    issues: list[DesignIssue]


class HomeDesignResponse(SpatialModel):
    task_id: int
    version: int
    document: HomeDesignDocument | None
    validation: DesignValidation | None = None
