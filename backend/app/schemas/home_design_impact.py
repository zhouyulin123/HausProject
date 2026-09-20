"""空间版本切换的只读影响契约。"""

from typing import Literal

from pydantic import Field

from app.schemas.home_design import DesignValidation, HomeDesignDocument
from app.schemas.spatial import SpatialDocument, SpatialModel


class SpaceImpactRequest(SpatialModel):
    document: HomeDesignDocument
    target_space_version: int = Field(ge=1, strict=True)


class SpaceChange(SpatialModel):
    entity_type: Literal["room", "wall", "opening", "space"]
    entity_id: str
    change: Literal["added", "removed", "modified"]


class ReferenceIssue(SpatialModel):
    entity_type: Literal["object", "surface", "point"]
    entity_id: str
    code: str
    message: str


class SpaceImpactResponse(SpatialModel):
    task_id: int
    source_space_version: int
    target_space_version: int
    target_space: SpatialDocument
    candidate_document: HomeDesignDocument
    changes: list[SpaceChange]
    reference_issues: list[ReferenceIssue]
    validation: DesignValidation | None
    can_apply: bool
