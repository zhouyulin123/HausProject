"""浏览器隔离验收服务：真实空间路由与临时 SQLite，不连接业务数据库。"""

import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import shutil

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from app.api.routes import spatial, home_design, home_design_delivery, home_design_agent, products, upload
from app.api.routes import home_delivery_snapshot
from app.core.config import settings
from app.db.database import Base, get_db
from app.db.models import CustomQuoteRule, DesignTask, UploadedImage, Product
from app.services.anonymous_session_service import create_anonymous_session, attach_task
from app.services.private_image_service import ProtectedUploadFiles


def create_app(*, stub_home_agent=False):
    if stub_home_agent:
        from app.services import llm_service

        def propose_fixture(*, instruction, context):
            available = context.get("available_assets") or []
            if available:
                asset = available[0]
                room = context["space"]["rooms"][0]
                existing_ids = {
                    item["id"] for item in context["document"].get("objects", [])
                }
                candidate_id = "ai-approved-chair"
                if candidate_id in existing_ids:
                    candidate_id = f"{candidate_id}-{len(existing_ids) + 1}"
                placement_x = 1.2 if not existing_ids else min(4.5, 1.2 + len(existing_ids) * 1.5)
                return {
                    "outcome": "proposal",
                    "message": "隔离验收建议：加入已授权家具，等待确认",
                    "operations": [
                        {
                            "type": "add_asset_object",
                            "id": candidate_id,
                            "asset_id": asset["asset_id"],
                            "room_id": room["id"],
                            "position": {"x": placement_x, "y": 0, "z": 1.2},
                            "rotation": 15,
                        }
                    ],
                }
            item = context["document"]["objects"][0]
            return {
                "outcome": "proposal",
                "message": "隔离验收建议：调整物件名称，等待确认",
                "operations": [{"type": "patch_object", "id": item["id"],
                                "changes": {"name": "AI验收收纳柜"}}],
            }

        llm_service.plan_home_design = propose_fixture
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs" / "v2-spatial-browser"
    output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="db-", dir=output)
    uploads = Path(temporary.name) / "uploads"
    uploads.mkdir()
    shutil.copyfile(root / "case_image" / "户型图1.png", uploads / "spatial-source.png")
    settings.upload_dir = str(uploads)
    engine = create_engine(
        f"sqlite+pysqlite:///{Path(temporary.name).as_posix()}/test.sqlite",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    from tests.unit.test_furniture_model_rules import _lounge_chair_spec
    from app.services.furniture_model_rules import compile_lounge_chair_rule
    from tests.unit.test_open_geometry_service import chair_design
    from app.schemas.open_geometry import OpenGeometryDesign
    from app.services.open_geometry_service import compile_open_geometry

    product_spec = _lounge_chair_spec()
    product_spec['确定性建模规则'] = compile_lounge_chair_rule(product_spec)
    product_bounds = product_spec['确定性建模规则']['包围尺寸_mm']
    design = OpenGeometryDesign.model_validate(chair_design())
    open_version = dict(version=1, source='llm', instruction='隔离测试夹具，非模型调用',
                        design=design.model_dump(mode='json'), model_spec=compile_open_geometry(design))
    fixture_state = {'open_geometry_furniture': {'current_version': 1, 'current': open_version, 'history': [open_version]}}
    with factory() as db:
        now = datetime.now(timezone.utc)
        db.add(Product(name='验收样板休闲椅', sku='BROWSER-CHAIR', price=0,
                       data_origin='public_reference', model_spec_json=product_spec))
        db.add(Product(name='验收商业休闲椅', sku='BROWSER-COMMERCIAL-CHAIR', price=680,
                       price_max=680, data_origin='merchant', source_name='隔离验收目录',
                       source_product_id='browser-chair', source_retrieved_at=now-timedelta(days=1),
                       price_observed_at=now-timedelta(days=1), verification_status='verified',
                       verified_at=now-timedelta(hours=1), verified_by='browser-reviewer',
                       data_version='browser-v1', availability_status='in_stock', stock_quantity=20,
                       region_codes=['CN-SH'], price_valid_from=now-timedelta(days=1),
                       price_valid_to=now+timedelta(days=1), model_width_mm=product_bounds['宽'],
                       model_height_mm=product_bounds['高'], model_depth_mm=product_bounds['深'],
                       model_spec_json=product_spec))
        db.add(CustomQuoteRule(project_name='验收地面铺装', category='表面材料',
                               pricing_unit='㎡', material_grade='耐磨地板', unit_price=100,
                               region_codes=['CN-SH'], waste_rate_bps=1000, minimum_quantity=10,
                               installation_fee=200, shipping_fee=100, tax_rate_bps=0,
                               data_version='browser-v1', record_version=1,
                               description='隔离验收规则：每个表面独立计价', is_active=True))
        owner = create_anonymous_session(db)
        stranger = create_anonymous_session(db)
        task = DesignTask(status="waiting_input")
        db.add(task)
        db.flush()
        attach_task(db, session_id=owner.id, task_id=task.id)
        image = UploadedImage(
            task_id=task.id,
            file_url="/uploads/spatial-source.png",
            file_name="原始户型图.png",
        )
        db.add(image)
        db.commit()
        fixture = {"task_id": task.id, "session_id": owner.id, "image_id": image.id,
                   "stranger_session_id": stranger.id}
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            engine.dispose()
            temporary.cleanup()

    app = FastAPI(lifespan=lifespan)
    app.state.temporary = temporary
    app.state.engine = engine

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.include_router(spatial.router, prefix="/api/design/tasks")
    app.include_router(home_design.router, prefix="/api/design/tasks")
    app.include_router(home_design_delivery.router, prefix="/api/design/tasks")
    app.include_router(home_delivery_snapshot.router, prefix="/api/design/tasks")
    app.include_router(home_delivery_snapshot.public_router, prefix="/api/home-shares")
    app.include_router(home_design_agent.router, prefix="/api/design/tasks")
    app.include_router(upload.router, prefix="/api/upload")
    app.include_router(products.router, prefix="/api/products")
    app.mount("/uploads", ProtectedUploadFiles(directory=str(uploads), session_factory=factory))

    @app.get("/fixture")
    def get_fixture():
        return fixture

    @app.post("/fixture")
    def new_fixture():
        with factory() as db:
            task = DesignTask(status="waiting_input", agent_state_json=fixture_state)
            db.add(task)
            db.flush()
            attach_task(db, session_id=fixture["session_id"], task_id=task.id)
            image = UploadedImage(
                task_id=task.id,
                file_url="/uploads/spatial-source.png",
                file_name="原始户型图.png",
            )
            db.add(image)
            alternate = UploadedImage(
                task_id=task.id,
                file_url="/uploads/spatial-source.png",
                file_name="修订户型图.png",
            )
            db.add(alternate)
            db.commit()
            return {
                "task_id": task.id,
                "session_id": fixture["session_id"],
                "image_id": image.id,
                "alternate_image_id": alternate.id,
                "stranger_session_id": fixture["stranger_session_id"],
            }

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--stub-home-agent", action="store_true")
    arguments = parser.parse_args()
    uvicorn.run(
        create_app(stub_home_agent=arguments.stub_home_agent), host="127.0.0.1", port=arguments.port, log_level="warning"
    )
