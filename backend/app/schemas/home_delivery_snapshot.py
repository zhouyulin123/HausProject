"""整屋交付冻结与明确授权分享请求。"""

from datetime import datetime
from typing import Literal
from pydantic import Field, StrictBool, field_serializer, model_validator
from app.schemas.spatial import SpatialModel
from app.schemas.spatial import SpatialRoom, SpatialWall, SpatialOpening
from app.schemas.home_design import (
    DesignSurface,
    DesignPoint,
    ObjectPosition,
    ObjectSize,
    Material,
    Installation,
    Clearance,
    PointRequirement,
    DesignValidation,
)


class PublicObject(SpatialModel):
    id: str
    room_id: str
    name: str
    category: Literal["furniture", "equipment", "lighting", "textile", "fixture"]
    position: ObjectPosition
    size: ObjectSize
    rotation: float
    material: Material
    installation: Installation | None = None
    clearance: Clearance | None = None
    point_requirement: PointRequirement | None = None


class PublicDocument(SpatialModel):
    schema_version: Literal["home-design/1.0"]
    space_version: int
    surfaces: list[DesignSurface]
    objects: list[PublicObject]
    points: list[DesignPoint] = Field(default_factory=list)


class PublicSpace(SpatialModel):
    schema_version: Literal["spatial/1.0"]
    unit: Literal["m"]
    scale_status: Literal["confirmed", "unconfirmed"]
    rooms: list[SpatialRoom]
    walls: list[SpatialWall]
    openings: list[SpatialOpening]


class PublicLine(SpatialModel):
    entity_type: str
    id: str
    room_id: str
    room_name: str
    name: str
    material: Material | None = None
    unit: str
    quantity: float | None
    quantity_status: str | None = None
    unit_price: int | None
    total_price: int | None
    price_status: str


class PublicGap(SpatialModel):
    code: str
    entity_type: str | None
    id: str | None


class PublicQuote(SpatialModel):
    currency: Literal["CNY"]
    known_subtotal: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    total_price: int | None
    created_at: str
    limitations: list[str]
    lines: list[PublicLine]


class PublicSnapshot(SpatialModel):
    schema_version: Literal["public-home-delivery/1.0"]
    home_version: int
    space_version: int
    document: PublicDocument
    space: PublicSpace
    lines: list[PublicLine]
    validation: DesignValidation
    gaps: list[PublicGap]
    limitations: list[str]
    quote: PublicQuote | None


class Mutation(SpatialModel):
    client_mutation_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")


class DeliveryCreate(Mutation):
    home_version: int = Field(ge=1, strict=True)
    quote_id: int | None = Field(default=None, ge=1, strict=True)


class DeliverySummary(SpatialModel):
    id: int = Field(ge=1, strict=True)
    task_id: int = Field(ge=1, strict=True)
    home_version: int = Field(ge=1, strict=True)
    space_version: int = Field(ge=1, strict=True)
    quote_id: int | None = Field(default=None, ge=1, strict=True)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime):
        return value.isoformat()


class DeliverySummaryPage(SpatialModel):
    items: list[DeliverySummary]
    next_before_id: int | None = Field(default=None, ge=1, strict=True)


class ConfirmationCreate(Mutation):
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["reviewed", "needs_changes"]
    note: str = Field(default="", max_length=1000)


class ShareCreate(Mutation):
    consent_public: StrictBool
    include_private_models: StrictBool = False
    include_source_image: StrictBool = False
    expires_in_hours: int = Field(default=168, ge=1, le=720, strict=True)

    @model_validator(mode="after")
    def explicit_scope(self):
        if (
            not self.consent_public
            or self.include_private_models
            or self.include_source_image
        ):
            raise ValueError(
                "必须明确授权公开户型与填写的名称；当前不支持分享原图或私有模型"
            )
        return self
