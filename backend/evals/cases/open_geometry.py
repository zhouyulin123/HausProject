"""开放几何合成开发集；只用于工程契约回归，不代表真实用户质量。"""

from __future__ import annotations

from copy import deepcopy


def _design() -> dict[str, object]:
    return {
        "schema_version": "furniture-open-geometry/1.0",
        "name": "连续包裹双人椅",
        "description": "开放几何合成开发样例",
        "scale": [1.0, 1.0, 1.0],
        "materials": [
            {
                "id": "fabric",
                "name": "米色织物",
                "base_color": "#D8C7AE",
                "roughness": 0.82,
                "metallic": 0.0,
            }
        ],
        "parts": [
            {
                "id": "seat",
                "name": "座面",
                "material_id": "fabric",
                "parent_id": None,
                "position_mm": [0.0, 430.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "geometry": {
                    "type": "box",
                    "size_mm": [1200.0, 120.0, 620.0],
                    "radius_mm": 50.0,
                },
            },
            {
                "id": "back",
                "name": "连续靠背",
                "material_id": "fabric",
                "parent_id": None,
                "position_mm": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "geometry": {
                    "type": "sweep",
                    "path_mm": [
                        [-560.0, 520.0, -260.0],
                        [0.0, 850.0, -320.0],
                        [560.0, 520.0, -260.0],
                    ],
                    "radius_mm": 105.0,
                    "tubular_segments": 40,
                    "radial_segments": 12,
                    "closed": False,
                },
            },
            {
                "id": "left_support",
                "name": "左支撑",
                "material_id": "fabric",
                "parent_id": None,
                "position_mm": [-500.0, 185.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "geometry": {
                    "type": "cylinder",
                    "radius_mm": 32.0,
                    "top_radius_mm": 32.0,
                    "height_mm": 370.0,
                    "radial_segments": 24,
                },
            },
            {
                "id": "right_support",
                "name": "右支撑",
                "material_id": "fabric",
                "parent_id": None,
                "position_mm": [500.0, 185.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "geometry": {
                    "type": "cylinder",
                    "radius_mm": 32.0,
                    "top_radius_mm": 32.0,
                    "height_mm": 370.0,
                    "radial_segments": 24,
                },
            },
        ],
    }


def synthetic_development_case() -> list[dict[str, object]]:
    design = _design()
    wrapped_back = deepcopy(design["parts"][1])
    wrapped_back["geometry"]["path_mm"][1][2] = -430.0
    left_support = deepcopy(design["parts"][2])
    right_support = deepcopy(design["parts"][3])
    left_support["geometry"]["radius_mm"] = 24.0
    left_support["geometry"]["top_radius_mm"] = 24.0
    right_support["geometry"]["radius_mm"] = 24.0
    right_support["geometry"]["top_radius_mm"] = 24.0
    return [
        {
            "id": "create",
            "instruction": "设计一把连续包裹的双人椅",
            "candidates": [{"operation": "create", "design": design}],
            "expected_code": "completed",
            "expected_version_delta": 1,
            "required_part_ids": ["seat", "back", "left_support", "right_support"],
        },
        {
            "id": "wrap-back",
            "instruction": "靠背再包裹一些",
            "candidates": [
                {"operation": "patch", "patch": {"upsert_parts": [wrapped_back]}}
            ],
            "expected_code": "completed",
            "expected_version_delta": 1,
            "preserve_part_ids": ["seat", "left_support", "right_support"],
            "preserve_material_ids": ["fabric"],
            "expected_values": {"parts.back.geometry.path_mm.1.2": -430.0},
        },
        {
            "id": "thin-supports",
            "instruction": "左右支撑做细，其他保持",
            "candidates": [
                {
                    "operation": "patch",
                    "patch": {"upsert_parts": [left_support, right_support]},
                }
            ],
            "expected_code": "completed",
            "expected_version_delta": 1,
            "preserve_part_ids": ["seat", "back"],
            "preserve_material_ids": ["fabric"],
            "expected_values": {
                "parts.left_support.geometry.radius_mm": 24.0,
                "parts.right_support.geometry.radius_mm": 24.0,
            },
        },
        {
            "id": "widen",
            "instruction": "整体加宽 10%",
            "candidates": [
                {"operation": "patch", "patch": {"scale": [1.1, 1.0, 1.0]}}
            ],
            "expected_code": "completed",
            "expected_version_delta": 1,
            "preserve_part_ids": ["seat", "back", "left_support", "right_support"],
            "preserve_material_ids": ["fabric"],
            "expected_values": {"scale.0": 1.1, "scale.1": 1.0, "scale.2": 1.0},
        },
        {
            "id": "repair",
            "instruction": "稍微加宽一点",
            "candidates": [
                {
                    "operation": "patch",
                    "patch": {"remove_part_ids": ["missing_part"]},
                },
                {"operation": "patch", "patch": {"scale": [1.15, 1.0, 1.0]}},
            ],
            "expected_code": "completed",
            "expected_version_delta": 1,
            "expected_planner_calls": 2,
            "expected_repair_code": "unknown_part",
            "preserve_material_ids": ["fabric"],
            "expected_values": {"scale.0": 1.15},
        },
        {
            "id": "unsupported",
            "instruction": "用任意 NURBS 和布尔雕刻重建",
            "candidates": [
                {
                    "operation": "unsupported",
                    "reason": "开放几何 v1 不支持 NURBS 和任意布尔运算",
                }
            ],
            "expected_code": "unsupported_geometry",
            "expected_version_delta": 0,
            "state_must_remain_unchanged": True,
        },
    ]
