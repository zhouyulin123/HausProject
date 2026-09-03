from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShareModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePlanShareRequest(ShareModel):
    plan_version_id: int = Field(ge=1)
    expires_in_hours: int = Field(default=168, ge=1, le=720)


class CreatePlanShareResponse(ShareModel):
    token: str
    share_url: str
    expires_at: datetime


class RevokePlanShareResponse(ShareModel):
    status: Literal["revoked"]


class SharedFurniture(ShareModel):
    sku: str | None = None
    name: str
    category: str | None = None
    room: str | None = None
    style: str | None = None
    material: str | None = None
    price_range: str | None = None
    size: str | None = None
    reason: str | None = None
    alternative: str | None = None
    quantity: float | None = None
    unit_price: int | None = None
    subtotal: int | None = None


class SharedColor(ShareModel):
    name: str
    hex: str
    usage: str | None = None


class SharedMaterial(ShareModel):
    name: str
    description: str | None = None


class SharedLighting(ShareModel):
    name: str
    purpose: str | None = None
    description: str | None = None


class SharedBudgetItem(ShareModel):
    name: str
    percent: float | None = None
    amount: int | None = None


class SharedQuoteLine(ShareModel):
    sku: str
    quantity: float
    unit_price: int
    subtotal: int


class SharedCustomQuoteLine(ShareModel):
    project: str
    grade: str | None = None
    unit: str | None = None
    quantity: float
    unit_price: int
    subtotal: int


class SharedQuote(ShareModel):
    currency: str
    furniture_total: int
    custom_total: int
    total: int
    line_items: list[SharedQuoteLine] = Field(default_factory=list)
    custom_line_items: list[SharedCustomQuoteLine] = Field(default_factory=list)


class PublicPlanSnapshot(ShareModel):
    name: str
    style: str | None = None
    description: str | None = None
    score: float | None = None
    budget: int | None = None
    tags: list[str] = Field(default_factory=list)
    suitable_for: list[str] = Field(default_factory=list)
    layout_suggestions: list[str] = Field(default_factory=list)
    ai_tips: list[str] = Field(default_factory=list)
    furniture: list[SharedFurniture] = Field(default_factory=list)
    colors: list[SharedColor] = Field(default_factory=list)
    materials: list[SharedMaterial] = Field(default_factory=list)
    lighting: list[SharedLighting] = Field(default_factory=list)
    budget_breakdown: list[SharedBudgetItem] = Field(default_factory=list)
    quote: SharedQuote | None = None


class PublicPlanShareResponse(ShareModel):
    expires_at: datetime
    plan: PublicPlanSnapshot
