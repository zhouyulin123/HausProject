"""统一动作规划合成开发集；不代表真实用户质量。"""

from __future__ import annotations

from copy import deepcopy


def _context(*, selected_instance_id: str | None = "chair-a") -> dict[str, object]:
    return {
        "activeMode": "custom_furniture",
        "scene": {
            "id": 23,
            "version": 4,
            "roomId": "living-room",
            "roomName": "客厅",
            "roomCenter": {"x": 0.0, "z": 0.0},
            "openings": [
                {"id": "window-east", "type": "window"},
                {"id": "door-south", "type": "door"},
            ],
        },
        "selectedInstanceId": selected_instance_id,
        "currentOpenGeometry": {
            "version": 3,
            "name": "包裹感双人椅",
            "modelId": "open-geometry-task-23-v3",
            "partIds": ["seat", "back", "left-support", "right-support"],
        },
        "openGeometryItems": [
            {
                "instanceId": "chair-a",
                "name": "chair-private-label",
                "openGeometryVersion": 3,
                "position": {"x": -0.8, "z": 0.4},
            },
            {
                "instanceId": "chair-b",
                "name": "另一把椅子",
                "openGeometryVersion": 2,
                "position": {"x": 0.9, "z": 0.4},
            },
        ],
        "openGeometryItemsTruncated": False,
    }


def synthetic_development_cases() -> list[dict[str, object]]:
    """返回独立副本，避免评测器或模型污染共享夹具。"""
    cases: list[dict[str, object]] = [
        {
            "id": "create-and-place",
            "instruction": "做一把圆润的单人椅并放到房间中间",
            "context": _context(selected_instance_id=None),
            "expected": {
                "outcome": "execute",
                "tools": ["open_geometry.edit", "scene.place_open_geometry"],
                "placement_kinds": ["room_center"],
            },
            "fixture_plan": {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "创建椅子并放到房间中间",
                "steps": [
                    {
                        "id": "shape",
                        "tool": "open_geometry.edit",
                        "instruction": "做一把圆润的单人椅",
                    },
                    {
                        "id": "place",
                        "tool": "scene.place_open_geometry",
                        "dependsOn": ["shape"],
                        "placement": {"kind": "room_center"},
                    },
                ],
            },
        },
        {
            "id": "edit-current",
            "instruction": "保持颜色，把靠背再包裹一些",
            "context": _context(),
            "expected": {
                "outcome": "execute",
                "tools": ["open_geometry.edit"],
            },
            "fixture_plan": {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "修改当前开放几何靠背",
                "steps": [
                    {
                        "id": "edit",
                        "tool": "open_geometry.edit",
                        "instruction": "保持颜色，把靠背再包裹一些",
                    }
                ],
            },
        },
        {
            "id": "move-near-opening",
            "instruction": "把选中的椅子移到东侧窗户附近",
            "context": _context(),
            "expected": {
                "outcome": "execute",
                "tools": ["scene.move_item"],
                "instance_id": "chair-a",
                "opening_id": "window-east",
                "placement_kinds": ["near_opening"],
            },
            "fixture_plan": {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "execute",
                "summary": "移动选中的椅子到东侧窗户附近",
                "steps": [
                    {
                        "id": "move",
                        "tool": "scene.move_item",
                        "instanceId": "chair-a",
                        "placement": {
                            "kind": "near_opening",
                            "openingId": "window-east",
                        },
                    }
                ],
            },
        },
        {
            "id": "ambiguous-target",
            "instruction": "把那把椅子挪到中间",
            "context": _context(selected_instance_id=None),
            "expected": {
                "outcome": "clarify",
                "question_field": "target_instance",
            },
            "fixture_plan": {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "clarify",
                "summary": "存在多个候选家具",
                "steps": [],
                "question": {
                    "field": "target_instance",
                    "prompt": "请选择要移动的椅子。",
                    "candidateIds": ["chair-a", "chair-b"],
                },
            },
        },
        {
            "id": "unsupported-tool",
            "instruction": "直接生成可下厂的榫卯加工刀路",
            "context": _context(),
            "expected": {
                "outcome": "unsupported",
                "reason_code": "unsupported_action",
            },
            "fixture_plan": {
                "schemaVersion": "agent-action-plan/1.0",
                "outcome": "unsupported",
                "summary": "当前白名单不支持制造刀路",
                "steps": [],
                "reasonCode": "unsupported_action",
            },
        },
    ]
    return deepcopy(cases)
