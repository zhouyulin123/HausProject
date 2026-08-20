import math

import pytest

from app.schemas.scenes import RoomGeometry, Vector2XZ
from app.services.layout_evaluator import PASS_THRESHOLD
from app.services.layout_generator import LayoutFurniture, generate_layouts


def _room(width: float = 6.0, depth: float = 5.0) -> RoomGeometry:
    return RoomGeometry(
        id="living-room",
        name="客厅",
        floor_polygon=[
            Vector2XZ(x=-width / 2, z=-depth / 2),
            Vector2XZ(x=width / 2, z=-depth / 2),
            Vector2XZ(x=width / 2, z=depth / 2),
            Vector2XZ(x=-width / 2, z=depth / 2),
        ],
        ceiling_height=2.8,
    )


def _furniture() -> list[LayoutFurniture]:
    return [
        LayoutFurniture("SOFA-001", "云朵三人沙发", "沙发", 2.2, 0.95, 0.85),
        LayoutFurniture("TV-CAB-001", "电视收纳柜", "柜子", 1.6, 0.4, 1.9),
        LayoutFurniture("TEA-001", "岩板茶几", "茶几", 1.0, 0.55, 0.42),
    ]


@pytest.mark.unit
def test_generate_layouts_returns_sorted_candidates():
    results = generate_layouts(_room(), [], _furniture())

    assert len(results) == 3
    totals = [score.total for _, score in results]
    assert totals == sorted(totals, reverse=True)
    # 最优候选应达到合格线
    assert results[0][1].total >= PASS_THRESHOLD


@pytest.mark.unit
def test_generate_layouts_sofa_and_tv_face_each_other():
    scene, score = generate_layouts(_room(), [], _furniture())[0]

    assert score.valid
    sofa = next(item for item in scene.items if item.category == "沙发")
    tv = next(item for item in scene.items if item.category == "柜子")

    # 沙发靠后墙（z 负），电视柜靠前墙（z 正）
    assert sofa.transform.position.z < 0
    assert tv.transform.position.z > 0
    # 电视柜面向沙发（绕 Y 轴 180°）
    assert abs(abs(tv.transform.rotation.y) - math.pi) < 1e-3
    # x 正对
    assert abs(sofa.transform.position.x - tv.transform.position.x) < 1e-6


@pytest.mark.unit
def test_generate_layouts_tea_table_in_front_of_sofa():
    scene, _ = generate_layouts(_room(), [], _furniture())[0]

    sofa = next(item for item in scene.items if item.category == "沙发")
    tea = next(item for item in scene.items if item.category == "茶几")

    assert tea.transform.position.z > sofa.transform.position.z
    assert abs(tea.transform.position.x - sofa.transform.position.x) < 1e-6


@pytest.mark.unit
def test_generate_layouts_items_have_real_dimensions():
    scene, _ = generate_layouts(_room(), [], _furniture())[0]

    for item in scene.items:
        assert item.dimensions is not None
        assert item.dimensions.x > 0
        assert item.dimensions.y > 0
        assert item.dimensions.z > 0
        # 家具中心高度应为高度的一半（落地摆放）
        assert item.transform.position.y == pytest.approx(
            item.dimensions.y / 2
        )


@pytest.mark.unit
def test_generate_layouts_empty_furniture_returns_empty():
    assert generate_layouts(_room(), [], []) == []
