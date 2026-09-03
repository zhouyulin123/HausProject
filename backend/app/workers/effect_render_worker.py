"""独立消费效果图任务；FastAPI 请求进程不会调用 SD。"""

from __future__ import annotations

import argparse
from hashlib import sha256
import logging
import os
from pathlib import Path
import socket
import tempfile
import threading
import time

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.request_context import bind_request_id
from app.db.database import SessionLocal
from app.db.models import EffectRenderJob, UploadedImage
from app.services import effect_render_job_service, sd_service
from app.services.sd_service import SDUnavailable


logger = logging.getLogger(__name__)


def _heartbeat(
    stop: threading.Event,
    *,
    job_id: int,
    worker_id: str,
    worker_attempt: int,
) -> None:
    while not stop.wait(settings.effect_render_worker_heartbeat_seconds):
        with SessionLocal() as db:
            if not effect_render_job_service.renew_lease(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                lease_seconds=settings.effect_render_worker_lease_seconds,
            ):
                return


def _load_input(job_id: int) -> tuple[str, bytes | None, str | None]:
    with SessionLocal() as db:
        job = db.get(EffectRenderJob, job_id)
        if job is None:
            raise RuntimeError("效果图任务不存在")
        room_bytes = None
        if job.source_image_id is not None:
            image = db.get(UploadedImage, job.source_image_id)
            if image is None or image.task_id != job.task_id or not image.file_url:
                raise RuntimeError("效果图输入图片快照不存在")
            path = Path(settings.upload_dir) / Path(image.file_url).name
            if not path.is_file():
                raise RuntimeError("效果图输入图片文件不存在")
            room_bytes = path.read_bytes()
            actual_digest = f"sha256:{sha256(room_bytes).hexdigest()}"
            if job.source_image_digest and actual_digest != job.source_image_digest:
                raise RuntimeError("效果图输入图片已变化，拒绝执行非快照输入")
        return job.prompt_snapshot, room_bytes, job.request_id


def _publish_bytes(
    png_bytes: bytes, *, job_id: int, worker_attempt: int
) -> tuple[Path, str]:
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("效果图输出不是有效 PNG")
    output_dir = Path(settings.upload_dir).resolve() / "effect_renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_name = f"effect_job{job_id}_a{worker_attempt}.png"
    final_path = output_dir / final_name
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{final_name}.", suffix=".tmp", dir=output_dir
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(png_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, final_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return final_path, f"/uploads/effect_renders/{final_name}"


def process_one_job(*, worker_id: str) -> bool:
    with SessionLocal() as db:
        job = effect_render_job_service.claim_next_job(
            db,
            worker_id=worker_id,
            lease_seconds=settings.effect_render_worker_lease_seconds,
            retry_delay_seconds=settings.effect_render_worker_retry_base_seconds,
        )
        if job is None:
            return False
        job_id = job.id
        worker_attempt = job.attempt_count

    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        kwargs={
            "stop": stop,
            "job_id": job_id,
            "worker_id": worker_id,
            "worker_attempt": worker_attempt,
        },
        daemon=True,
    )
    heartbeat.start()
    final_path: Path | None = None
    try:
        prompt, room_bytes, request_id = _load_input(job_id)
        with bind_request_id(request_id):
            if not sd_service.is_available():
                with SessionLocal() as db:
                    effect_render_job_service.fail_job(
                        db,
                        job_id=job_id,
                        worker_id=worker_id,
                        worker_attempt=worker_attempt,
                        error_message="效果图生成服务未启用",
                        retryable=False,
                        retry_delay_seconds=0,
                        terminal_status="provider_unavailable",
                    )
                return True
            png_bytes, mode = sd_service.render_effect_image(prompt, room_bytes)

        with SessionLocal() as db:
            if not effect_render_job_service.mark_progress(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                progress=90,
            ):
                return True
        final_path, output_url = _publish_bytes(
            png_bytes, job_id=job_id, worker_attempt=worker_attempt
        )
        with SessionLocal() as db:
            completed = effect_render_job_service.complete_job(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                image_url=output_url,
                mode=mode,
            )
        if not completed:
            final_path.unlink(missing_ok=True)
        else:
            logger.info("效果图任务完成: job_id=%s", job_id)
    except SDUnavailable as exc:
        logger.warning("效果图供应商调用失败: job_id=%s error=%s", job_id, exc)
        with SessionLocal() as db:
            effect_render_job_service.fail_job(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error_message="效果图生成失败，请稍后重试",
                retryable=True,
                retry_delay_seconds=(
                    settings.effect_render_worker_retry_base_seconds
                    * (2 ** max(0, worker_attempt - 1))
                ),
            )
    except (OSError, RuntimeError, ValueError):
        logger.exception("效果图任务执行失败: job_id=%s", job_id)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        with SessionLocal() as db:
            effect_render_job_service.fail_job(
                db,
                job_id=job_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error_message="效果图任务输入或输出无效",
                retryable=False,
                retry_delay_seconds=0,
            )
    finally:
        stop.set()
        heartbeat.join(timeout=1)
    return True


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="豪斯效果图 Worker")
    parser.add_argument("--once", action="store_true", help="最多处理一个任务")
    parser.add_argument("--worker-id", default=_default_worker_id())
    args = parser.parse_args()
    configure_logging()
    while True:
        processed = process_one_job(worker_id=args.worker_id)
        if args.once:
            return 0
        if not processed:
            time.sleep(settings.effect_render_worker_poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
