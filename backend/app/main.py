from pathlib import Path

import os
import re

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.main import api_router
from app.core.config import settings
from app.core.request_context import bind_request_id, normalize_request_id
from app.db.database import get_db
from app.db.schema_readiness import database_schema_is_current


_BUILD_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


app = FastAPI(
    title="AI Home Decor API",
    description="Backend API for AI customized home decoration assistant",
    version="0.2.0",
    debug=settings.app_debug,
)

# 前端开发服务器直连时需要 CORS（生产环境走同域或网关时可收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

# 本地上传文件的静态访问
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    with bind_request_id(request_id):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    build_digest = os.getenv("APP_BUILD_DIGEST", "").strip()
    if _BUILD_DIGEST_PATTERN.fullmatch(build_digest):
        response.headers["X-App-Build-Digest"] = build_digest
    return response


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.app_env}


@app.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    checks = {
        "database": "ok",
        "database_schema": "not_checked",
        "storage": "ok",
        "llm": "configured" if settings.llm_api_key else "not_configured",
    }
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "unavailable"
    else:
        try:
            checks["database_schema"] = (
                "ok" if database_schema_is_current(db) else "migration_required"
            )
        except Exception:
            checks["database_schema"] = "migration_required"

    upload_path = Path(settings.upload_dir)
    if not upload_path.is_dir() or not os.access(upload_path, os.W_OK):
        checks["storage"] = "unavailable"

    required_checks_ok = all(
        checks[name] == "ok"
        for name in ("database", "database_schema", "storage")
    )
    payload = {
        "status": "ready" if required_checks_ok else "unavailable",
        "environment": settings.app_env,
        "checks": checks,
    }
    if not required_checks_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload
