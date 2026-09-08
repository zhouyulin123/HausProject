from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import Product
from app.schemas.scene_agent import SceneOperationBatch
from app.schemas.scenes import SceneDocument
from app.services.scene_service import (
    assert_scene_catalog_deliverable,
    assert_scene_catalog_mutation,
    validate_scene,
)
from app.services.scene_tools import (
    SceneCatalogEligibilityError,
    SceneToolError,
    apply_scene_operations,
    build_scene_agent_context,
)


VALID_FROM = datetime(2020, 1, 1, tzinfo=timezone.utc)
VALID_TO = datetime(2100, 1, 1, tzinfo=timezone.utc)


def _eligible_product(**values) -> Product:
    defaults = {
        "data_origin": "merchant",
        "verification_status": "verified",
        "availability_status": "in_stock",
        "region_codes": ["*"],
        "stock_quantity": 10,
        "price_valid_from": VALID_FROM,
        "price_valid_to": VALID_TO,
        "verified_at": VALID_FROM,
        "verified_by": "tester",
        "data_version": "catalog-test-v1",
    }
    defaults.update(values)
    return Product(**defaults)


def _scene(*, second_item: bool = False) -> SceneDocument:
    items = [
        {
            "instanceId": "sofa-main",
            "sku": "SOFA-001",
            "category": "沙发",
            "dimensions": {"x": 2, "y": 0.8, "z": 1},
            "transform": {
                "position": {"x": 0, "y": 0.4, "z": -1},
                "rotation": {"x": 0, "y": 0, "z": 0},
                "scale": {"x": 1, "y": 1, "z": 1},
            },
        }
    ]
    if second_item:
        items.append(
            {
                "instanceId": "table-main",
                "sku": "TABLE-001",
                "category": "茶几",
                "dimensions": {"x": 1, "y": 0.4, "z": 0.6},
                "transform": {
                    "position": {"x": 0, "y": 0.2, "z": 0.5},
                    "rotation": {"x": 0, "y": 0, "z": 0},
                    "scale": {"x": 1, "y": 1, "z": 1},
                },
            }
        )
    return SceneDocument.model_validate(
        {
            "room": {
                "id": "living-room",
                "name": "客厅",
                "floorPolygon": [
                    {"x": -2.5, "z": -2},
                    {"x": 2.5, "z": -2},
                    {"x": 2.5, "z": 2},
                    {"x": -2.5, "z": 2},
                ],
                "ceilingHeight": 2.8,
                "wallThickness": 0.12,
            },
            "openings": [
                {
                    "id": "door-main",
                    "type": "door",
                    "wallIndex": 0,
                    "offset": 2.1,
                    "width": 0.9,
                    "height": 2.1,
                    "sillHeight": 0,
                }
            ],
            "items": items,
        }
    )


@pytest.fixture
def scene_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                _eligible_product(
                    sku="SOFA-001",
                    name="测试沙发",
                    category="沙发",
                    room="客厅",
                    style="现代简约",
                    price=6000,
                    model_width_mm=2000,
                    model_height_mm=800,
                    model_depth_mm=1000,
                    is_active=True,
                ),
                _eligible_product(
                    sku="TABLE-001",
                    name="测试茶几",
                    category="茶几",
                    room="客厅",
                    style="现代简约",
                    price=1600,
                    model_width_mm=1000,
                    model_height_mm=400,
                    model_depth_mm=600,
                    is_active=True,
                ),
                _eligible_product(
                    sku="CHAIR-001",
                    name="测试单椅",
                    category="餐椅",
                    room="客厅",
                    style="现代简约",
                    price=900,
                    model_width_mm=500,
                    model_height_mm=900,
                    model_depth_mm=500,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        yield db


@pytest.mark.unit
def test_scene_tools_apply_whitelisted_operations_without_mutating_source(scene_db):
    source = _scene(second_item=True)
    before = deepcopy(source.model_dump())
    batch = SceneOperationBatch.model_validate(
        {
            "message": "已调整沙发并增加单椅",
            "operations": [
                {
                    "type": "move",
                    "instanceId": "sofa-main",
                    "position": {"x": -0.8, "z": -1},
                },
                {
                    "type": "rotate",
                    "instanceId": "table-main",
                    "rotationY": 1.5707963268,
                },
                {"type": "remove", "instanceId": "table-main"},
                {
                    "type": "add",
                    "sku": "CHAIR-001",
                    "position": {"x": 1.4, "z": 0.8},
                    "rotationY": -0.4,
                },
            ],
        }
    )

    result = apply_scene_operations(scene_db, source, batch.operations)

    assert source.model_dump() == before
    assert result.items[0].transform.position.x == -0.8
    assert all(item.instance_id != "table-main" for item in result.items)
    chair = next(item for item in result.items if item.sku == "CHAIR-001")
    assert chair.instance_id == "item-CHAIR-001-1"
    assert chair.dimensions.model_dump() == {"x": 0.5, "y": 0.9, "z": 0.5}
    assert chair.transform.position.y == 0.45


@pytest.mark.unit
def test_scene_tools_reject_unknown_instance_and_missing_dimensions(scene_db):
    with pytest.raises(SceneToolError, match="不存在"):
        apply_scene_operations(
            scene_db,
            _scene(),
            SceneOperationBatch.model_validate(
                {
                    "message": "移动",
                    "operations": [
                        {
                            "type": "move",
                            "instanceId": "missing",
                            "position": {"x": 0, "z": 0},
                        }
                    ],
                }
            ).operations,
        )

    product = scene_db.scalar(
        select(Product).where(Product.sku == "CHAIR-001")
    )
    product.model_width_mm = None
    scene_db.commit()
    with pytest.raises(SceneToolError, match="三维尺寸"):
        apply_scene_operations(
            scene_db,
            _scene(),
            SceneOperationBatch.model_validate(
                {
                    "message": "新增",
                    "operations": [
                        {
                            "type": "add",
                            "sku": "CHAIR-001",
                            "position": {"x": 0, "z": 0},
                        }
                    ],
                }
            ).operations,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"verification_status": "draft"}, "verification_required"),
        ({"availability_status": "out_of_stock"}, "out_of_stock"),
        (
            {"price_valid_to": datetime(2020, 1, 2, tzinfo=timezone.utc)},
            "price_expired",
        ),
    ],
)
def test_scene_agent_excludes_and_rejects_ineligible_catalog_products(
    scene_db,
    changes,
    reason_code,
):
    product = scene_db.scalar(select(Product).where(Product.sku == "CHAIR-001"))
    for field, value in changes.items():
        setattr(product, field, value)
    scene_db.commit()

    context = build_scene_agent_context(scene_db, _scene())
    assert "CHAIR-001" not in {item["sku"] for item in context["catalog"]}

    operations = SceneOperationBatch.model_validate(
        {
            "message": "新增单椅",
            "operations": [
                {
                    "type": "add",
                    "sku": "CHAIR-001",
                    "position": {"x": 1.2, "z": 0.8},
                }
            ],
        }
    ).operations
    with pytest.raises(SceneCatalogEligibilityError) as captured:
        apply_scene_operations(scene_db, _scene(), operations)

    assert captured.value.code == "catalog_product_ineligible"
    assert captured.value.sku == "CHAIR-001"
    assert reason_code in captured.value.reason_codes


@pytest.mark.unit
def test_scene_agent_exposes_and_adds_eligible_catalog_product(scene_db):
    context = build_scene_agent_context(scene_db, _scene())
    assert "CHAIR-001" in {item["sku"] for item in context["catalog"]}

    operations = SceneOperationBatch.model_validate(
        {
            "message": "新增单椅",
            "operations": [
                {
                    "type": "add",
                    "sku": "CHAIR-001",
                    "position": {"x": 1.2, "z": 0.8},
                }
            ],
        }
    ).operations
    updated = apply_scene_operations(scene_db, _scene(), operations)
    assert "CHAIR-001" in {item.sku for item in updated.items}


@pytest.mark.unit
def test_expired_historical_sku_remains_readable_but_cannot_be_reintroduced_or_delivered(
    scene_db,
):
    product = scene_db.scalar(select(Product).where(Product.sku == "SOFA-001"))
    product.price_valid_to = datetime(2020, 1, 2, tzinfo=timezone.utc)
    scene_db.commit()
    historical = _scene()

    # 历史快照的几何校验与读取不依赖商品当前经营状态。
    assert validate_scene(scene_db, historical).valid is True
    assert_scene_catalog_mutation(scene_db, before=historical, after=historical)

    replacement = historical.model_copy(deep=True)
    replacement.items[0].instance_id = "replacement-sofa"
    with pytest.raises(SceneCatalogEligibilityError) as mutation_error:
        assert_scene_catalog_mutation(
            scene_db,
            before=historical,
            after=replacement,
        )
    assert mutation_error.value.reason_codes == ("price_expired",)

    with pytest.raises(SceneCatalogEligibilityError) as delivery_error:
        assert_scene_catalog_deliverable(scene_db, historical)
    assert delivery_error.value.code == "catalog_product_ineligible"
    assert delivery_error.value.reason_codes == ("price_expired",)

@pytest.mark.unit
def test_scene_validation_reports_full_footprint_outside_room(scene_db):
    scene = _scene()
    scene.items[0].transform.position.x = 2.2

    report = validate_scene(scene_db, scene)

    assert "item_exceeds_room" in {warning.code for warning in report.warnings}


@pytest.mark.unit
def test_scene_validation_reports_rotated_furniture_collision(scene_db):
    scene = _scene(second_item=True)
    scene.items[1].transform.position.z = -0.6
    scene.items[1].transform.rotation.y = 0.3

    report = validate_scene(scene_db, scene)

    assert "item_collision" in {warning.code for warning in report.warnings}


@pytest.mark.unit
def test_scene_validation_reports_blocked_door_clearance(scene_db):
    scene = _scene()
    scene.items[0].transform.position.z = -1.6

    report = validate_scene(scene_db, scene)

    assert "door_clearance_blocked" in {
        warning.code for warning in report.warnings
    }
