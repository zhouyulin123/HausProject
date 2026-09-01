from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CabinetMaterial = Literal[
    "E0 颗粒板",
    "多层实木",
    "实木（橡木）",
    "E0 颗粒板（防潮封边）",
]
TableMaterial = Literal[
    "实木（橡木）",
    "岩板 + 金属",
    "多层实木 + 岩板台面",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CabinetDimensions(StrictModel):
    width_mm: int = Field(ge=400, le=5000)
    height_mm: int = Field(ge=600, le=3000)
    depth_mm: int = Field(ge=250, le=1000)


class CabinetStructure(StrictModel):
    door_style: Literal["hinged", "sliding", "open"]
    door_count: int = Field(ge=0, le=10)
    compartment_count: int = Field(ge=1, le=12)
    shelf_count: int = Field(ge=0, le=24)
    drawer_count: int = Field(ge=0, le=12)
    panel_thickness_mm: int = Field(ge=16, le=25)
    leg_height_mm: int = Field(ge=0, le=250)

    @model_validator(mode="after")
    def validate_door_configuration(self) -> "CabinetStructure":
        if self.door_style == "open" and self.door_count != 0:
            raise ValueError("开放式柜体的 door_count 必须为 0")
        if self.door_style != "open" and self.door_count < 1:
            raise ValueError("带门柜体的 door_count 必须大于 0")
        if self.door_style == "sliding" and self.door_count < 2:
            raise ValueError("sliding 柜门至少需要 2 扇门")
        return self


class CabinetSpec(StrictModel):
    family: Literal["cabinet"]
    name: str = Field(min_length=1, max_length=100)
    purpose: Literal[
        "wardrobe",
        "entryway_cabinet",
        "bookcase",
        "balcony_storage",
    ]
    material: CabinetMaterial
    dimensions: CabinetDimensions
    structure: CabinetStructure

    @model_validator(mode="after")
    def validate_buildable_structure(self) -> "CabinetSpec":
        inner_width = self.dimensions.width_mm - 2 * self.structure.panel_thickness_mm
        if inner_width / self.structure.compartment_count < 250:
            raise ValueError("每个柜体分区的净宽不能小于 250mm")
        if (
            self.structure.door_style == "sliding"
            and self.dimensions.width_mm < 1000
        ):
            raise ValueError("sliding 柜门要求柜体宽度至少为 1000mm")
        usable_height = (
            self.dimensions.height_mm
            - self.structure.leg_height_mm
            - 2 * self.structure.panel_thickness_mm
        )
        if usable_height < 500:
            raise ValueError("柜体腿高和板厚使内部净高小于 500mm")
        return self


class TableDimensions(StrictModel):
    width_mm: int = Field(ge=600, le=3000)
    height_mm: int = Field(ge=650, le=1100)
    depth_mm: int = Field(ge=450, le=1600)


class TableStructure(StrictModel):
    top_shape: Literal["rectangle", "round"]
    base_style: Literal["four_leg", "pedestal", "trestle"]
    support_count: int = Field(ge=1, le=4)
    seat_count: int = Field(ge=1, le=12)
    top_thickness_mm: int = Field(ge=18, le=80)
    edge_radius_mm: int = Field(ge=0, le=80)

    @model_validator(mode="after")
    def validate_base_configuration(self) -> "TableStructure":
        expected_supports = {
            "four_leg": 4,
            "pedestal": 1,
            "trestle": 2,
        }
        if self.support_count != expected_supports[self.base_style]:
            raise ValueError(
                f"{self.base_style} 的 support_count 必须为 "
                f"{expected_supports[self.base_style]}"
            )
        return self


class TableSpec(StrictModel):
    family: Literal["table"]
    name: str = Field(min_length=1, max_length=100)
    purpose: Literal["dining_table", "desk", "kitchen_island"]
    material: TableMaterial
    dimensions: TableDimensions
    structure: TableStructure

    @model_validator(mode="after")
    def validate_top_dimensions(self) -> "TableSpec":
        if (
            self.structure.top_shape == "round"
            and self.dimensions.width_mm != self.dimensions.depth_mm
        ):
            raise ValueError("圆桌的宽度和深度必须一致")
        if self.structure.top_thickness_mm >= self.dimensions.height_mm:
            raise ValueError("台面厚度必须小于家具高度")
        return self


CustomFurnitureSpec = Annotated[
    CabinetSpec | TableSpec,
    Field(discriminator="family"),
]


class CustomFurniturePreviewRequest(StrictModel):
    spec: CustomFurnitureSpec


class CustomFurnitureQuotePreview(StrictModel):
    status: Literal["estimated", "needs_human"]
    reason_code: Literal[
        "quote_rule_missing",
        "quote_rule_ambiguous",
        "quote_rule_invalid",
    ] | None = None
    rule_id: int | None = None
    project_name: str
    material_grade: str
    pricing_unit: str | None = None
    unit_price: int | None = None
    quantity: Decimal | None = None
    estimated_amount: Decimal | None = None
    currency: Literal["CNY"] = "CNY"
    description: str | None = None


class CustomFurniturePreviewResult(StrictModel):
    status: Literal["preview_ready", "needs_human"]
    spec: CustomFurnitureSpec
    model_spec: dict[str, Any]
    quote_preview: CustomFurnitureQuotePreview
    warnings: list[str] = Field(default_factory=list)


class CustomFurniturePreviewResponse(CustomFurniturePreviewResult):
    task_id: int
