"""开发案例使用实际目录工具，但不提供真实客户或 LLM 质量证明。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import Base
from app.db.models import Product
from evals.development_catalog_cases import build_cases, run_suite


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "development_catalog_enabled", True)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        for index, (room, category) in enumerate([
            ("客厅", "沙发"), ("卧室", "床"), ("餐厅", "餐桌"), ("书房", "书桌"),
        ]):
            db.add(Product(sku=f"DEV-{index}", name=f"开发{category}", room=room,
                           category=category, price=1000, style="原木风", is_active=True,
                           data_origin="development_fixture", verification_status="draft",
                           source_name="开发假设", source_product_id=f"DEV-{index}",
                           source_retrieved_at=now, price_observed_at=now,
                           data_version="dev-1", availability_status="in_stock", stock_quantity=20,
                           region_codes=["CN"], price_valid_from=now-timedelta(days=1),
                           price_valid_to=now+timedelta(days=30),
                           model_width_mm=1200, model_depth_mm=600, model_height_mm=750))
        db.commit()
        yield db
    engine.dispose()


def test_cases_cover_rooms_and_catalog_with_explicit_assumptions(catalog):
    cases = build_cases(catalog)
    assert len(cases) >= 20
    assert {c["task_input"]["space_type"] for c in cases} == {"客厅", "卧室", "餐厅", "书房"}
    assert len({c["case_id"] for c in cases}) == len(cases)
    assert all(c["origin"] == "synthetic" and c["assumptions"] for c in cases)
    assert {sku for c in cases for sku in c["requested_skus"]} == {f"DEV-{i}" for i in range(4)}
    report = run_suite(catalog, cases)
    assert report["failed"] == 0
    assert report["passed"] == len(cases)
    assert report["llm_accuracy"] is None
    assert report["production_acceptance"] is False
    assert all(row["quote"]["total"] == 1000 and row["scene"]["items"] for row in report["cases"])


def test_stock_failure_is_not_hidden_by_case_generation(catalog):
    cases = build_cases(catalog)
    catalog.query(Product).filter(Product.sku == "DEV-0").update({"stock_quantity": 0})
    catalog.commit()
    report = run_suite(catalog, cases)
    failed = [row for row in report["cases"] if not row["passed"]]
    assert len(failed) == 5
    assert all("out_of_stock" in row["failures"] for row in failed)


def test_empty_catalog_and_duplicate_cases_fail_closed(catalog):
    cases = build_cases(catalog)
    with pytest.raises(ValueError, match="重复"):
        run_suite(catalog, [cases[0], cases[0]])
    catalog.query(Product).delete()
    catalog.commit()
    with pytest.raises(ValueError, match="开发商品"):
        build_cases(catalog)


def test_disabled_development_mode_does_not_create_success(catalog, monkeypatch):
    cases = build_cases(catalog)
    monkeypatch.setattr(settings, "development_catalog_enabled", False)
    report = run_suite(catalog, cases)
    assert report["failed"] == len(cases)


def test_missing_sku_and_impossible_geometry_are_reported(catalog):
    cases = build_cases(catalog)
    cases[0]["requested_skus"] = ["MISSING"]
    cases[1]["room"]["floor_polygon"] = [
        {"x": -0.2, "z": -0.2}, {"x": 0.2, "z": -0.2},
        {"x": 0.2, "z": 0.2}, {"x": -0.2, "z": 0.2},
    ]
    cases[1]["openings"] = []
    report = run_suite(catalog, cases[:2])
    assert report["failed"] == 2
    assert "product_missing" in report["cases"][0]["failures"]
    assert "layout_empty" in report["cases"][0]["failures"]
    assert "layout_invalid" in report["cases"][1]["failures"]


def test_development_report_refuses_real_origin(catalog):
    cases = build_cases(catalog)
    cases[0]["origin"] = "private_real"
    with pytest.raises(ValueError, match="synthetic"):
        run_suite(catalog, cases)
