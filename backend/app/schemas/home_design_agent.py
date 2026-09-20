"""整屋受控建议契约；候选必须经用户确认后另行保存。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.home_design import (
    DesignObject,
    DesignSurface,
    DesignValidation,
    HomeDesignDocument,
    Material,
    ObjectPosition,
    ObjectSize,
)
from app.schemas.spatial import SpatialModel


class ObjectChanges(SpatialModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r".*\S.*"
    )
    room_id: str | None = Field(default=None, min_length=1, max_length=100)
    position: ObjectPosition | None = None
    size: ObjectSize | None = None
    rotation: float | None = Field(default=None, ge=-360, le=360)
    material: Material | None = None

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("修改字段不能为空或 null")
        return self


class AddObject(SpatialModel):
    type: Literal["add_object"]
    object: DesignObject


class AddAssetObject(SpatialModel):
    """只引用任务内冻结资产；其名称、尺寸和材质由服务端填充。"""

    type: Literal["add_asset_object"]
    id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    asset_id: int = Field(ge=1, strict=True)
    room_id: str = Field(min_length=1, max_length=100)
    position: ObjectPosition
    rotation: float = Field(ge=-360, le=360)


class PatchObject(SpatialModel):
    type: Literal["patch_object"]
    id: str = Field(min_length=1, max_length=100)
    changes: ObjectChanges


class RemoveObject(SpatialModel):
    type: Literal["remove_object"]
    id: str = Field(min_length=1, max_length=100)


class AddSurface(SpatialModel):
    type: Literal["add_surface"]
    surface: DesignSurface

    @model_validator(mode="after")
    def reject_quote_rule_binding(self):
        if self.surface.quote_rule_id is not None:
            raise ValueError("AI 不能绑定材料计价规则，必须由用户显式选择")
        return self


class PatchSurface(SpatialModel):
    type: Literal["patch_surface"]
    id: str = Field(min_length=1, max_length=100)
    material: Material


class RemoveSurface(SpatialModel):
    type: Literal["remove_surface"]
    id: str = Field(min_length=1, max_length=100)


Operation = Annotated[
    AddObject
    | AddAssetObject
    | PatchObject
    | RemoveObject
    | AddSurface
    | PatchSurface
    | RemoveSurface,
    Field(discriminator="type"),
]


class HomeDesignAgentPlan(SpatialModel):
    outcome: Literal["proposal", "clarify", "unsupported"]
    message: str = Field(min_length=1, max_length=1500, pattern=r".*\S.*")
    operations: list[Operation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def outcome_matches_operations(self):
        if (self.outcome == "proposal") != bool(self.operations):
            raise ValueError("只有建议可以携带操作，建议不得为空")
        return self


class HomeDesignAgentRequest(SpatialModel):
    client_turn_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    base_version: int = Field(ge=1, strict=True)
    space_version: int = Field(ge=1, strict=True)
    message: str = Field(min_length=1, max_length=4000, pattern=r".*\S.*")
    region: str | None = Field(
        default=None, min_length=2, max_length=32, pattern=r"^[A-Z0-9-]+$"
    )
    budget_max: int | None = Field(default=None, gt=0, strict=True)
    allowed_asset_ids: list[Annotated[int, Field(ge=1, strict=True)]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def unique_assets(self):
        if len(set(self.allowed_asset_ids)) != len(self.allowed_asset_ids):
            raise ValueError("家具快照标识不能重复")
        return self


class HomeAgentAssetEvidence(SpatialModel):
    asset_id: int
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: int
    source_version: int


class HomeAgentEvidence(SpatialModel):
    schema_version: Literal["home-agent-evidence/1.0"] = "home-agent-evidence/1.0"
    asset_refs: list[HomeAgentAssetEvidence] = Field(default_factory=list)
    rule_version: Literal["catalog-eligibility/home-agent-budget/1.0"] = (
        "catalog-eligibility/home-agent-budget/1.0"
    )

    @model_validator(mode="after")
    def unique_asset_refs(self):
        if len({item.asset_id for item in self.asset_refs}) != len(self.asset_refs):
            raise ValueError("证据中的家具快照不能重复")
        return self


class HomeAgentBudgetPreview(SpatialModel):
    region: str | None = None
    currency: Literal["CNY"] = "CNY"
    known_subtotal: int = Field(default=0, ge=0)
    pending_count: int = Field(default=0, ge=0)
    total_price: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, gt=0)
    budget_status: Literal["unknown", "incomplete", "within", "over"] = "unknown"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_totals(self):
        if self.region is None and (
            self.total_price is not None or self.budget_status != "unknown"
        ):
            raise ValueError("没有地区时不能形成价格或预算结论")
        if self.pending_count and self.total_price is not None:
            raise ValueError("存在待询价项时不能形成完整总价")
        if self.total_price is not None and self.known_subtotal != self.total_price:
            raise ValueError("完整总价必须与已知小计一致")
        if self.budget_status in {"within", "over"}:
            if self.total_price is None or self.budget_max is None:
                raise ValueError("预算结论缺少完整总价或预算上限")
            within = self.total_price <= self.budget_max
            if within != (self.budget_status == "within"):
                raise ValueError("预算结论与金额不一致")
        if self.budget_status == "incomplete" and self.total_price is not None:
            raise ValueError("不完整预算不能携带总价")
        return self


class HomeDesignAgentResponse(SpatialModel):
    turn_id: int
    outcome: Literal["proposal", "clarify", "unsupported", "invalid"]
    message: str
    candidate_document: HomeDesignDocument | None = None
    validation: DesignValidation | None = None
    base_version: int
    space_version: int
    evidence: HomeAgentEvidence = Field(default_factory=HomeAgentEvidence)
    budget_preview: HomeAgentBudgetPreview = Field(default_factory=HomeAgentBudgetPreview)

    @model_validator(mode="after")
    def consistent_candidate(self):
        if self.outcome == "proposal":
            if (
                self.candidate_document is None
                or self.validation is None
                or not self.validation.valid
                or self.validation.issues
            ):
                raise ValueError("建议必须包含通过检查的候选")
            if self.candidate_document.space_version != self.space_version:
                raise ValueError("候选空间版本不一致")
        elif self.candidate_document is not None:
            raise ValueError("非建议不得携带可应用候选")
        return self


class HomeDesignAgentHistoryItem(SpatialModel):
    turn_id: int
    client_turn_id: str
    message: str
    base_version: int
    space_version: int
    status: Literal["running", "completed", "failed"]
    response: HomeDesignAgentResponse | None = None
    error_code: str | None = None
    created_at: datetime


class HomeDesignAgentHistory(SpatialModel):
    task_id: int
    turns: list[HomeDesignAgentHistoryItem]
    next_before_id: int | None = None
