"""显式启用的材料计价规则 MySQL 并发验收。"""

from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import require_factory
from app.api.routes import products
from app.core.config import settings
from app.db.database import get_db
from app.db.models import CustomQuoteRule


@pytest.mark.integration
def test_mysql_quote_rule_concurrent_expected_version_allows_one_writer():
    if os.environ.get("HAUS_RUN_MYSQL_QUOTE_RULE_TESTS") != "1":
        pytest.skip("本机材料规则 MySQL 并发验收未显式启用")
    url = make_url(settings.database_url)
    assert url.get_backend_name() == "mysql" and url.host in {"localhost", "127.0.0.1"}
    engine = create_engine(
        settings.database_url,
        pool_size=4,
        max_overflow=0,
        isolation_level="REPEATABLE READ",
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    rule_id = None
    try:
        with factory() as db:
            rule = CustomQuoteRule(
                project_name="并发验收地面铺装",
                category="表面材料",
                pricing_unit="㎡",
                material_grade="耐磨地板",
                unit_price=100,
                region_codes=["CN-SH"],
                data_version="mysql-concurrency-v1",
                record_version=1,
                is_active=True,
            )
            db.add(rule)
            db.commit()
            rule_id = rule.id

        app = FastAPI()
        app.include_router(products.router, prefix="/api/products")

        def override_db():
            with factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_factory] = lambda: object()

        lock_session = factory()
        lock_session.scalar(
            select(CustomQuoteRule)
            .where(CustomQuoteRule.id == rule_id)
            .with_for_update()
        )

        def patch(price):
            with TestClient(app) as client:
                response = client.patch(
                    f"/api/products/quote-rules/{rule_id}",
                    json={"expected_record_version": 1, "unit_price": price},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(patch, 110)
            second = pool.submit(patch, 120)
            lock_session.commit()
            outcomes = [first.result(timeout=20), second.result(timeout=20)]
        lock_session.close()

        assert sorted(status for status, _ in outcomes) == [200, 409]
        conflict = next(body for status, body in outcomes if status == 409)
        assert conflict["detail"]["code"] == "record_version_conflict"
        with factory() as db:
            current = db.get(CustomQuoteRule, rule_id)
            assert current.record_version == 2
            assert current.unit_price in {110, 120}
    finally:
        if rule_id is not None:
            with factory() as db:
                db.execute(delete(CustomQuoteRule).where(CustomQuoteRule.id == rule_id))
                db.commit()
        engine.dispose()
