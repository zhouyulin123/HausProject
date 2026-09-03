"""独立轮询 Blender 渲染作业；API 进程不会导入 bpy 或执行客户代码。"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.db.database import SessionLocal
from app.db.models import BlenderRenderJob, DesignSceneVersion, Product
from app.schemas.scenes import SceneDocument
from app.services import blender_job_service, product_asset_service
from app.services.blender_render_service import (
    BlenderOutputError,
    build_blender_command,
    build_render_manifest,
    publish_render_output,
)


logger = logging.getLogger(__name__)
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class BlenderProcessError(RuntimeError):
    """受监管 Blender 子进程未成功结束。"""


def approved_product_model_urls(
    products: list[Product],
    *,
    allow_uploaded_models: bool,
) -> dict[str, str | None]:
    """在统一审核门禁之后应用当前 Blender 部署的路径策略。"""
    result: dict[str, str | None] = {}
    for product in products:
        if not product.sku:
            continue
        contract = product_asset_service.product_asset_contract(product)
        model_url = contract["approved_model_url"]
        if model_url and not (
            model_url.startswith("/models/") or allow_uploaded_models
        ):
            model_url = None
        result[product.sku] = model_url
    return result


def resolve_blender_executable(configured: str) -> Path:
    candidate = Path(configured)
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate.resolve()
        raise BlenderProcessError("配置的 Blender 可执行文件不存在")
    discovered = shutil.which(configured)
    if discovered:
        return Path(discovered).resolve()
    local_runtime = (
        Path(__file__).resolve().parents[2]
        / ".runtime"
        / "blender"
        / "blender.exe"
    )
    if configured == "blender" and local_runtime.is_file():
        return local_runtime
    raise BlenderProcessError(
        "未找到 Blender，请安装后配置 BLENDER_EXECUTABLE"
    )


def execute_blender_process(
    *,
    executable: Path,
    script_path: Path,
    manifest_path: Path,
    output_path: Path,
    timeout_seconds: int,
    runner: ProcessRunner = subprocess.run,
    base_environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """以固定参数、无 shell、无 Python 注入环境运行可信脚本。"""
    environment = dict(base_environment or os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    command = build_blender_command(
        executable=executable,
        script_path=script_path,
        manifest_path=manifest_path,
        output_path=output_path,
    )
    completed = runner(
        command,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=environment,
        cwd=str(manifest_path.parent),
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        ),
    )
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout or "")[-4000:]
        raise BlenderProcessError(
            f"Blender 渲染进程退出码 {completed.returncode}\n{diagnostic}"
        )
    for line in (completed.stdout or "").splitlines():
        if line.startswith("HAUS_RENDER_"):
            logger.info("%s", line)
    return completed


def _load_job_payload(job_id: int) -> tuple[SceneDocument, dict[str, str | None], BlenderRenderJob]:
    with SessionLocal() as db:
        job = db.get(BlenderRenderJob, job_id)
        if job is None:
            raise BlenderProcessError("渲染任务不存在")
        version = db.get(DesignSceneVersion, job.scene_version_id)
        if version is None:
            raise BlenderProcessError("渲染任务对应的场景版本不存在")
        scene = SceneDocument.model_validate(version.scene_json)
        skus = {item.sku for item in scene.items}
        products = db.scalars(
            select(Product).where(
                Product.sku.in_(skus),
                Product.is_active.is_(True),
            )
        ).all() if skus else []
        model_urls = approved_product_model_urls(
            products,
            allow_uploaded_models=settings.blender_allow_uploaded_models,
        )
        db.expunge(job)
        return scene, model_urls, job


def process_one_job(*, worker_id: str, executable: Path) -> bool:
    lease_seconds = settings.blender_render_timeout_seconds + 120
    with SessionLocal() as db:
        job = blender_job_service.claim_next_job(
            db,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_attempts=settings.blender_worker_max_attempts,
        )
        if job is None:
            return False
        job_id = job.id
        worker_attempt = job.attempt

    try:
        scene, model_urls, detached_job = _load_job_payload(job_id)
        upload_root = Path(settings.upload_dir).resolve()
        work_root = Path(settings.blender_work_dir).resolve()
        public_root = Path(settings.frontend_public_dir).resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        manifest = build_render_manifest(
            scene=scene,
            product_model_urls=model_urls,
            upload_root=upload_root,
            frontend_public_root=public_root,
            profile=detached_job.profile,
        )
        script_path = Path(__file__).with_name(
            "blender_scene_renderer.py"
        ).resolve()

        with tempfile.TemporaryDirectory(
            prefix=f"render-job-{job_id}-",
            dir=work_root,
        ) as temporary_directory:
            job_dir = Path(temporary_directory)
            manifest_path = job_dir / "manifest.json"
            temporary_output = job_dir / "render.png"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            with SessionLocal() as db:
                still_owned = blender_job_service.mark_progress(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    progress=30,
                )
            if not still_owned:
                logger.warning(
                    "Blender 渲染未启动：作业已失去租约 job_id=%s",
                    job_id,
                )
                return True
            execute_blender_process(
                executable=executable,
                script_path=script_path,
                manifest_path=manifest_path,
                output_path=temporary_output,
                timeout_seconds=settings.blender_render_timeout_seconds,
            )
            final_name = (
                f"scene_{detached_job.scene_id}_"
                f"v{detached_job.scene_version}_"
                f"{detached_job.profile}_"
                f"job{job_id}_a{worker_attempt}.png"
            )
            final_path = upload_root / "blender_renders" / final_name
            with SessionLocal() as db:
                still_owned = blender_job_service.mark_progress(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    progress=90,
                )
            if not still_owned:
                raise BlenderProcessError("Blender 渲染作业已失去有效租约")
            publish_render_output(
                temporary_output,
                final_path,
                max_bytes=settings.blender_render_max_mb * 1024 * 1024,
            )

        output_url = f"/uploads/blender_renders/{final_name}"
        with SessionLocal() as db:
            completed = blender_job_service.mark_completed(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                output_url=output_url,
            )
        if completed:
            logger.info("Blender 渲染完成: job_id=%s", job_id)
        else:
            logger.warning("Blender 渲染结果未发布：作业已失去租约 job_id=%s", job_id)
    except subprocess.TimeoutExpired:
        logger.exception("Blender 渲染超时: job_id=%s", job_id)
        with SessionLocal() as db:
            blender_job_service.mark_failed(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error_message="Blender 渲染超时",
            )
    except (BlenderProcessError, BlenderOutputError, OSError, ValueError):
        logger.exception("Blender 渲染失败: job_id=%s", job_id)
        with SessionLocal() as db:
            blender_job_service.mark_failed(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error_message="Blender 渲染失败，请稍后重试",
            )
    return True


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="豪斯 Blender 渲染 Worker")
    parser.add_argument("--once", action="store_true", help="最多处理一个任务")
    parser.add_argument("--worker-id", default=_default_worker_id())
    args = parser.parse_args()
    configure_logging()
    try:
        executable = resolve_blender_executable(settings.blender_executable)
    except BlenderProcessError as error:
        logger.error("%s", error)
        return 2

    while True:
        processed = process_one_job(
            worker_id=args.worker_id,
            executable=executable,
        )
        if args.once:
            return 0
        if not processed:
            time.sleep(settings.blender_worker_poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
