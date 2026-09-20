"""上传住宅原图只允许带会话鉴权读取，静态路径按登记事实拒绝。"""

from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import require_active_session, require_owned_design_task
from app.db.database import SessionLocal
from app.db.models import UploadedImage
from app.services.anonymous_session_service import session_owns_images


def registered_path(root: Path, file_url: str) -> Path:
    parts = urlsplit(file_url)
    path = unquote(parts.path)
    if (
        parts.scheme
        or parts.netloc
        or not path.startswith("/uploads/")
        or "\\" in path
        or "\x00" in path
    ):
        raise ValueError("原图路径无效")
    relative = path.removeprefix("/uploads/")
    if not relative or any(segment in (".", "..") for segment in relative.split("/")):
        raise ValueError("原图路径无效")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("原图路径越界")
    return result


def private_image_response(db, *, image_id: int, session_id: str, directory: str):
    require_active_session(db, session_id)
    image = db.get(UploadedImage, image_id)
    if image is None:
        raise HTTPException(404, detail="原图不存在或无权访问")
    if image.task_id is not None:
        require_owned_design_task(db, session_id=session_id, task_id=image.task_id)
    elif not session_owns_images(db, session_id, [image_id]):
        raise HTTPException(404, detail="原图不存在或无权访问")
    try:
        path = registered_path(Path(directory).resolve(), image.file_url or "")
        if not path.is_file():
            raise ValueError("原图文件不存在")
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(404, detail="原图不存在或无权访问") from exc
    return FileResponse(
        path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    )


def is_private_upload(directory: str, path: str, session_factory) -> bool:
    root = Path(directory).resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        return True
    with session_factory() as db:
        urls = db.scalars(
            select(UploadedImage.file_url).where(UploadedImage.file_url.is_not(None))
        ).all()
        for url in urls:
            registered = registered_path(root, url)
            if registered == candidate or (
                candidate.exists()
                and registered.exists()
                and candidate.samefile(registered)
            ):
                return True
    return False


class ProtectedUploadFiles(StaticFiles):
    """数据库不可用时不静默退回公共静态服务；不按文件名推测私有性。"""

    def __init__(self, *, directory, session_factory=SessionLocal):
        super().__init__(directory=directory)
        self.session_factory = session_factory

    async def get_response(self, path, scope):
        try:
            private = await run_in_threadpool(
                is_private_upload, str(self.directory), path, self.session_factory
            )
        except Exception:
            return JSONResponse(
                {"detail": "上传资源暂不可用"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        if private:
            return JSONResponse(
                {"detail": "Not Found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )
        return await super().get_response(path, scope)
