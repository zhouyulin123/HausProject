"""定制报价规则冻结证据的严格读取契约。"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return "".join([head, *[part.title() for part in tail]])


class CustomRuleEvidence(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    schema_version: Literal["1.0"]
    checked_at: datetime
    region: StrictStr | None
    is_active: StrictBool
    rule_id: StrictInt = Field(ge=1)
    data_version: StrictStr = Field(min_length=1, max_length=100)
    record_version: StrictInt = Field(ge=1)
    project: StrictStr = Field(min_length=1, max_length=100)
    grade: StrictStr = Field(min_length=1, max_length=100)
    pricing_unit: StrictStr = Field(min_length=1, max_length=20)
    unit_price: StrictInt = Field(ge=0)
    rule_region_codes: list[StrictStr]
    requested_quantity: float = Field(gt=0)
    billable_quantity: float = Field(gt=0)
    waste_rate_bps: StrictInt = Field(ge=0, le=10_000)
    minimum_quantity: float = Field(ge=0)
    base_subtotal: StrictInt = Field(ge=0)
    installation_fee: StrictInt = Field(ge=0)
    shipping_fee: StrictInt = Field(ge=0)
    tax_rate_bps: StrictInt = Field(ge=0, le=10_000)
    tax_amount: StrictInt = Field(ge=0)
    subtotal: StrictInt = Field(ge=0)

    @field_validator(
        "requested_quantity",
        "billable_quantity",
        "minimum_quantity",
        mode="before",
    )
    @classmethod
    def require_real_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("定制规则数量必须为数字")
        return value

    @model_validator(mode="after")
    def validate_normalized_values(self) -> "CustomRuleEvidence":
        if self.checked_at.tzinfo is None:
            raise ValueError("冻结规则检查时间必须携带时区")
        if not all(
            isfinite(value)
            for value in (
                self.requested_quantity,
                self.billable_quantity,
                self.minimum_quantity,
            )
        ):
            raise ValueError("冻结规则数量必须是有限值")
        if self.region is not None and (
            not self.region.strip() or self.region != self.region.strip().upper()
        ):
            raise ValueError("冻结规则地区必须规范化")
        codes = self.rule_region_codes
        if codes != sorted(set(codes)) or any(
            not code.strip() or code != code.strip().upper() for code in codes
        ):
            raise ValueError("冻结规则地区事实必须规范化且去重")
        return self
