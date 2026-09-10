"""统一对话动作规划的严格白名单契约。"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from app.schemas.scenes import SceneModel, Vector2XZ


class RoomCenterPlacement(SceneModel):
    kind: Literal["room_center"]


class NearOpeningPlacement(SceneModel):
    kind: Literal["near_opening"]
    opening_id: str = Field(min_length=1, max_length=100)


class ExplicitPlacement(SceneModel):
    kind: Literal["explicit"]
    position: Vector2XZ


ActionPlacement = Annotated[
    Union[RoomCenterPlacement, NearOpeningPlacement, ExplicitPlacement],
    Field(discriminator="kind"),
]


class ActionStep(SceneModel):
    id: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
    )
    depends_on: list[str] = Field(default_factory=list, max_length=2)


class OpenGeometryEditAction(ActionStep):
    tool: Literal["open_geometry.edit"]
    instruction: str = Field(min_length=2, max_length=1000)


class PlaceOpenGeometryAction(ActionStep):
    tool: Literal["scene.place_open_geometry"]
    placement: ActionPlacement


class MoveSceneItemAction(ActionStep):
    tool: Literal["scene.move_item"]
    instance_id: str = Field(min_length=1, max_length=100)
    placement: ActionPlacement


AgentAction = Annotated[
    Union[
        OpenGeometryEditAction,
        PlaceOpenGeometryAction,
        MoveSceneItemAction,
    ],
    Field(discriminator="tool"),
]


class ActionClarification(SceneModel):
    field: Literal["target_instance", "opening", "scene_context"]
    prompt: str = Field(min_length=2, max_length=300)
    candidate_ids: list[str] = Field(default_factory=list, max_length=20)


class AgentActionPlan(SceneModel):
    schema_version: Literal["agent-action-plan/1.0"]
    outcome: Literal["execute", "clarify", "unsupported"]
    summary: str = Field(min_length=1, max_length=300)
    steps: list[AgentAction] = Field(default_factory=list, max_length=3)
    question: ActionClarification | None = None
    reason_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def validate_outcome_and_steps(self) -> "AgentActionPlan":
        if self.outcome == "execute":
            if not self.steps:
                raise ValueError("execute 动作计划至少需要一个步骤")
            if self.question is not None or self.reason_code is not None:
                raise ValueError("execute 动作计划不得携带追问或不支持原因")
        elif self.outcome == "clarify":
            if self.steps or self.question is None or self.reason_code is not None:
                raise ValueError("clarify 动作计划只能携带一个追问")
        elif self.steps or self.question is not None or self.reason_code is None:
            raise ValueError("unsupported 动作计划只能携带稳定原因码")

        seen: set[str] = set()
        tools: list[str] = []
        for step in self.steps:
            if step.id in seen:
                raise ValueError("动作步骤 id 不得重复")
            if len(step.depends_on) != len(set(step.depends_on)):
                raise ValueError("动作步骤依赖不得重复")
            if any(dependency not in seen for dependency in step.depends_on):
                raise ValueError("动作步骤只能依赖更早的步骤")
            seen.add(step.id)
            tools.append(step.tool)

        if len(tools) != len(set(tools)):
            raise ValueError("P0 动作计划中同一工具最多执行一次")
        if "scene.move_item" in tools and len(tools) != 1:
            raise ValueError("P0 移动物件不能与创建或放置组合执行")
        if "open_geometry.edit" in tools and "scene.place_open_geometry" in tools:
            edit_index = tools.index("open_geometry.edit")
            place_index = tools.index("scene.place_open_geometry")
            if place_index <= edit_index:
                raise ValueError("开放几何必须先创建或修改，再加入场景")
            edit_id = self.steps[edit_index].id
            if edit_id not in self.steps[place_index].depends_on:
                raise ValueError("放置步骤必须显式依赖开放几何步骤")
        return self
