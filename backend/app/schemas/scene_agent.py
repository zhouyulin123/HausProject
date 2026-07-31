"""Scene Agent 只能生成的白名单空间操作契约。"""

from typing import Annotated, Literal, Union

from pydantic import Field

from app.schemas.scenes import (
    SceneModel,
    SceneResponse,
    Vector2XZ,
)


class MoveSceneItem(SceneModel):
    type: Literal["move"]
    instance_id: str = Field(min_length=1, max_length=100)
    position: Vector2XZ


class RotateSceneItem(SceneModel):
    type: Literal["rotate"]
    instance_id: str = Field(min_length=1, max_length=100)
    rotation_y: float = Field(ge=-6.2831853072, le=6.2831853072)


class RemoveSceneItem(SceneModel):
    type: Literal["remove"]
    instance_id: str = Field(min_length=1, max_length=100)


class AddSceneItem(SceneModel):
    type: Literal["add"]
    sku: str = Field(min_length=1, max_length=50)
    position: Vector2XZ
    rotation_y: float = Field(default=0, ge=-6.2831853072, le=6.2831853072)


SceneOperation = Annotated[
    Union[
        MoveSceneItem,
        RotateSceneItem,
        RemoveSceneItem,
        AddSceneItem,
    ],
    Field(discriminator="type"),
]


class SceneOperationBatch(SceneModel):
    message: str = Field(min_length=1, max_length=500)
    operations: list[SceneOperation] = Field(min_length=1, max_length=12)


class SceneAgentCommandRequest(SceneModel):
    base_version: int = Field(ge=1)
    instruction: str = Field(min_length=2, max_length=1000)


class SceneAgentCommandResponse(SceneModel):
    message: str
    operations: list[SceneOperation]
    scene: SceneResponse
