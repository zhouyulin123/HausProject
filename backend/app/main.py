from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.main import api_router
from app.core.config import settings


app = FastAPI(
    title="AI Home Decor API",
    description="Backend API for AI customized home decoration assistant",
    version="0.2.0",
    debug=settings.app_debug,
)

# 前端开发服务器直连时需要 CORS（生产环境走同域或网关时可收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

# 本地上传文件的静态访问
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.app_env}
