"""冻结商品资格证据的严格读取契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)


class FrozenEligibilityModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda name: "".join(
            [name.split("_")[0], *[part.title() for part in name.split("_")[1:]]]
        ),
        populate_by_name=True,
        extra="forbid",
    )


class FrozenProductDimensions(FrozenEligibilityModel):
    width: StrictInt | None
    depth: StrictInt | None
    height: StrictInt | None


class FrozenPolicyDimensions(FrozenEligibilityModel):
    width: StrictInt | None = None
    depth: StrictInt | None = None
    height: StrictInt | None = None


class FrozenEligibilityPolicy(FrozenEligibilityModel):
    region: StrictStr | None
    allow_draft: StrictBool
    allow_development: StrictBool = False
    max_unit_price: StrictInt | None = Field(default=None, ge=0)
    max_dimensions_mm: FrozenPolicyDimensions


class FrozenEligibilityFacts(FrozenEligibilityModel):
    is_active: StrictBool
    data_origin: StrictStr | None
    source_name: StrictStr | None
    source_url: StrictStr | None
    source_product_id: StrictStr | None
    source_retrieved_at: datetime | None
    price_observed_at: datetime | None
    verification_status: StrictStr | None
    verified_at: datetime | None
    verified_by: StrictStr | None
    data_version: StrictStr | None
    availability_status: StrictStr | None
    stock_quantity: StrictInt | None = Field(default=None, ge=0)
    lead_time_days_min: StrictInt | None = Field(default=None, ge=0)
    lead_time_days_max: StrictInt | None = Field(default=None, ge=0)
    price_valid_from: datetime | None
    price_valid_to: datetime | None
    region_codes: list[StrictStr]
    dimensions_mm: FrozenProductDimensions


class FrozenProductEligibilitySnapshot(FrozenEligibilityModel):
    schema_version: Literal["1.1"]
    checked_at: datetime
    sku: StrictStr = Field(min_length=1, max_length=100)
    quantity: StrictInt = Field(ge=1)
    unit_price: StrictInt = Field(ge=0)
    data_version: StrictStr = Field(min_length=1, max_length=100)
    record_version: StrictInt = Field(ge=1)
    policy: FrozenEligibilityPolicy
    facts: FrozenEligibilityFacts
    eligible: StrictBool
    reason_codes: list[StrictStr]

    @model_validator(mode="after")
    def validate_normalized_evidence(self) -> "FrozenProductEligibilitySnapshot":
        timestamps = (
            self.checked_at,
            self.facts.source_retrieved_at,
            self.facts.price_observed_at,
            self.facts.verified_at,
            self.facts.price_valid_from,
            self.facts.price_valid_to,
        )
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("冻结商品资格时间必须携带时区")
        if self.policy.region is not None and (
            not self.policy.region.strip()
            or self.policy.region != self.policy.region.strip().upper()
        ):
            raise ValueError("冻结商品资格地区必须规范化")
        codes = self.facts.region_codes
        if codes != sorted(set(codes)) or any(
            not code.strip() or code != code.strip().upper() for code in codes
        ):
            raise ValueError("冻结商品资格地区事实必须规范化且去重")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("冻结商品资格原因码不得重复")
        return self
