"""任务内冻结家具的可信引用契约。"""

from typing import Literal, Any
from pydantic import Field
from app.schemas.spatial import SpatialModel
from app.schemas.home_design import Material, ObjectSize


class AssetCreate(SpatialModel):
    client_mutation_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    kind: Literal["product", "open_geometry"]
    source_id: int = Field(ge=1, strict=True)
    source_version: int = Field(ge=1, strict=True)


class AssetResponse(SpatialModel):
    id: int
    task_id: int
    kind: Literal["product", "open_geometry"]
    source_id: int
    source_version: int
    name: str
    size: ObjectSize
    material: Material
    model_spec: dict[str, Any]
    content_digest: str
    source_summary: dict[str, str | None] = Field(default_factory=dict)
