from pathlib import Path

import logging
import os
import re
from time import perf_counter

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.main import api_router
from app.core.config import settings
from app.core.request_context import bind_request_id, normalize_request_id
from app.db.database import get_db
from app.db.schema_readiness import database_schema_is_current
from app.services import worker_presence_service
from app.services.private_image_service import ProtectedUploadFiles


_BUILD_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
http_logger = logging.getLogger("app.http")


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
app.mount("/uploads", ProtectedUploadFiles(directory=settings.upload_dir), name="uploads")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    log_path = request.url.path
    if log_path.startswith("/api/home-shares/"):
        log_path = "/api/home-shares/[redacted]"
    elif log_path.startswith("/api/shares/"):
        log_path = "/api/shares/[redacted]"
    elif log_path.startswith("/api/design/shares/"):
        log_path = "/api/design/shares/[redacted]/revoke"
    started_at = perf_counter()
    with bind_request_id(request_id):
        try:
            response = await call_next(request)
        except Exception:
            http_logger.exception(
                "HTTP request failed",
                extra={
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "http_method": request.method,
                    "http_path": log_path,
                    "status_code": 500,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            raise
        http_logger.info(
            "HTTP request completed",
            extra={
                "event": "http_request_completed",
                "request_id": request_id,
                "http_method": request.method,
                "http_path": log_path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if "Referrer-Policy" not in response.headers:
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    build_digest = os.getenv("APP_BUILD_DIGEST", "").strip()
    if _BUILD_DIGEST_PATTERN.fullmatch(build_digest):
        response.headers["X-App-Build-Digest"] = build_digest
    return response


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.app_env}


def _model_readiness(
    *,
    api_key: str,
    input_price_per_mtok: float | None,
    output_price_per_mtok: float | None,
) -> str:
    if not api_key:
        return "not_configured"
    if input_price_per_mtok is None or output_price_per_mtok is None:
        return "cost_guard_unconfigured"
    return "ready"


@app.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    checks = {
        "database": "ok",
        "database_schema": "not_checked",
        "storage": "ok",
        "llm": _model_readiness(
            api_key=settings.llm_api_key,
            input_price_per_mtok=settings.llm_input_price_per_mtok,
            output_price_per_mtok=settings.llm_output_price_per_mtok,
        ),
        "vl": _model_readiness(
            api_key=settings.vl_api_key,
            input_price_per_mtok=settings.vl_input_price_per_mtok,
            output_price_per_mtok=settings.vl_output_price_per_mtok,
        ),
        "workers": {"status": "unavailable", "required": {}},
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

    if checks["database_schema"] == "ok":
        try:
            worker_snapshot = worker_presence_service.readiness_snapshot(
                db,
                stale_after_seconds=settings.worker_readiness_timeout_seconds,
            )
        except Exception:
            pass
        else:
            checks["workers"] = {
                "status": "ok" if worker_snapshot.ready else "unavailable",
                "required": {
                    worker_type: {
                        "status": check.status,
                        "activeWorkers": check.active_workers,
                        "lastHeartbeatAt": (
                            check.last_heartbeat_at.isoformat().replace("+00:00", "Z")
                            if check.last_heartbeat_at is not None
                            else None
                        ),
                        "staleAfterSeconds": check.stale_after_seconds,
                    }
                    for worker_type, check in worker_snapshot.checks.items()
                },
            }

    upload_path = Path(settings.upload_dir)
    if not upload_path.is_dir() or not os.access(upload_path, os.W_OK):
        checks["storage"] = "unavailable"

    required_checks_ok = all(
        checks[name] == "ok"
        for name in ("database", "database_schema", "storage")
    ) and checks["workers"]["status"] == "ok"
    if settings.app_env == "production":
        required_checks_ok = required_checks_ok and all(
            checks[name] == "ready" for name in ("llm", "vl")
        )
    payload = {
        "status": "ready" if required_checks_ok else "unavailable",
        "environment": settings.app_env,
        "checks": checks,
    }
    if not required_checks_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload
