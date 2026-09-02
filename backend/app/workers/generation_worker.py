"""可恢复的方案生成 Worker；API 进程只入队，不负责执行模型调用。"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import inspect
import logging
import os
import socket
import threading
import time

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import DesignTask, GenerationRun
from app.services import generation_run_service


logger = logging.getLogger(__name__)
GenerationExecutor = Callable[..., object]


def _heartbeat_loop(
    *,
    stop: threading.Event,
    run_id: int,
    worker_id: str,
    worker_attempt: int,
) -> None:
    while not stop.wait(settings.generation_worker_heartbeat_seconds):
        with SessionLocal() as db:
            renewed = generation_run_service.renew_lease(
                db,
                run_id=run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                lease_seconds=settings.generation_worker_lease_seconds,
            )
        if not renewed:
            logger.warning("生成任务续租失败，停止心跳: run_id=%s", run_id)
            stop.set()
            return


def process_one_run(
    *,
    worker_id: str,
    executor: GenerationExecutor | None = None,
    start_heartbeat: bool = True,
    run_id: int | None = None,
) -> bool:
    """认领并处理一个任务；返回是否认领到了任务。"""
    with SessionLocal() as db:
        run = generation_run_service.claim_next_run(
            db,
            worker_id=worker_id,
            lease_seconds=settings.generation_worker_lease_seconds,
            execution_timeout_seconds=(
                settings.generation_worker_execution_timeout_seconds
            ),
            run_id=run_id,
            retry_delay_seconds=settings.generation_worker_retry_base_seconds,
        )
        if run is None:
            return False
        claimed_run_id = run.id
        task_id = run.task_id
        worker_attempt = run.attempt_count

    heartbeat_stop = threading.Event()
    heartbeat: threading.Thread | None = None
    if start_heartbeat:
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            kwargs={
                "stop": heartbeat_stop,
                "run_id": claimed_run_id,
                "worker_id": worker_id,
                "worker_attempt": worker_attempt,
            },
            daemon=True,
            name=f"generation-heartbeat-{claimed_run_id}",
        )
        heartbeat.start()

    try:
        with SessionLocal() as db:
            task = db.get(DesignTask, task_id)
            run = db.get(GenerationRun, claimed_run_id)
            if task is None or run is None:
                if run is not None:
                    generation_run_service.mark_failed(
                        db,
                        run=run,
                        worker_id=worker_id,
                        worker_attempt=worker_attempt,
                        error_message="设计任务不存在",
                        retryable=False,
                    )
                return True

            def persist_step(step):
                event = generation_run_service.record_step(
                    db,
                    run=run,
                    step=step,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                )
                if event is None:
                    raise generation_run_service.GenerationRunOwnershipError(
                        "方案生成任务已失去租约或被取消"
                    )
                task.progress = min(99, 50 + run.progress // 2)
                db.commit()

            def persist_meta(payload):
                if not generation_run_service.record_generation_meta(
                    db,
                    run=run,
                    meta=payload["meta"],
                    output_snapshot=payload["output_snapshot"],
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    commit=False,
                ):
                    raise generation_run_service.GenerationRunOwnershipError(
                        "方案生成任务已失去租约或被取消"
                    )

            def before_persist():
                heartbeat_stop.set()
                if heartbeat is not None:
                    heartbeat.join(timeout=5)
                owned = generation_run_service.assert_worker_ownership(
                    db,
                    run_id=claimed_run_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    lock=True,
                )
                if owned is None:
                    raise generation_run_service.GenerationRunOwnershipError(
                        "方案生成任务已失去租约或被取消"
                    )

            finalized = False

            def persist_success(generator: str):
                nonlocal finalized
                finalized = generation_run_service.mark_completed(
                    db,
                    run_id=claimed_run_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    generator=generator,
                    commit=False,
                )
                if not finalized:
                    raise generation_run_service.GenerationRunOwnershipError(
                        "方案生成结果提交前已失去租约"
                    )

            if executor is None:
                # 延迟导入，避免 API 路由与 worker 模块形成导入环。
                from app.api.routes.tasks import _execute_generation

                selected_executor = _execute_generation
            else:
                selected_executor = executor
            executor_kwargs = {
                "task": task,
                "on_step": persist_step,
                "on_meta": persist_meta,
                "before_persist": before_persist,
            }
            if "on_success" in inspect.signature(selected_executor).parameters:
                executor_kwargs["on_success"] = persist_success
            response = selected_executor(db, **executor_kwargs)
            if finalized:
                db.commit()
            elif not generation_run_service.mark_completed(
                db,
                run_id=claimed_run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                generator=response.generator,
            ):
                raise generation_run_service.GenerationRunOwnershipError(
                    "方案生成结果提交前已失去租约"
                )
        logger.info("方案生成完成: run_id=%s", claimed_run_id)
    except generation_run_service.GenerationRunOwnershipError:
        logger.warning("方案生成执行已停止: run_id=%s", claimed_run_id)
        with SessionLocal() as db:
            cancelled = generation_run_service.mark_cancelled_by_worker(
                db,
                run_id=claimed_run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
            )
            if not cancelled:
                generation_run_service.recover_expired_runs(
                    db,
                    retry_delay_seconds=(
                        settings.generation_worker_retry_base_seconds
                    ),
                )
    except Exception as exc:
        logger.exception("方案生成失败: run_id=%s", claimed_run_id)
        with SessionLocal() as db:
            failed_run = db.get(GenerationRun, claimed_run_id)
            if failed_run is not None:
                generation_run_service.mark_failed(
                    db,
                    run=failed_run,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    error_message=str(exc),
                    retryable=True,
                    retry_delay_seconds=(
                        settings.generation_worker_retry_base_seconds
                        * (2 ** max(0, worker_attempt - 1))
                    ),
                )
    finally:
        heartbeat_stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=5)
    return True


def execute_specific_run(run_id: int) -> None:
    """仅供开发环境显式开启的请求进程内回退。"""
    process_one_run(
        worker_id=f"inline-{socket.gethostname()}-{os.getpid()}",
        run_id=run_id,
    )


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="豪斯方案生成 Worker")
    parser.add_argument("--once", action="store_true", help="最多处理一个任务")
    parser.add_argument("--worker-id", default=_default_worker_id())
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    while True:
        processed = process_one_run(worker_id=args.worker_id)
        if args.once:
            return 0
        if not processed:
            time.sleep(settings.generation_worker_poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
