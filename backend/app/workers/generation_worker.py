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
from app.core.logging_config import configure_logging
from app.core.request_context import bind_request_id
from app.db.database import SessionLocal
from app.db.models import DesignTask, GenerationRun
from app.services import (
    generation_output_service,
    generation_run_service,
    llm_service,
    provider_circuit_service,
)


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

            def persist_success(generator: str, result_revision_id: int):
                nonlocal finalized
                from app.services import generation_scene_service

                generation_scene_service.prepare_revision_scenes(
                    db,
                    revision_id=result_revision_id,
                )
                finalized = generation_run_service.mark_completed(
                    db,
                    run_id=claimed_run_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    generator=generator,
                    result_revision_id=result_revision_id,
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
            if executor is None:
                executor_kwargs["allow_template_fallback"] = not (
                    generation_run_service.is_agent_generation_run(run)
                )
            if "on_success" in inspect.signature(selected_executor).parameters:
                executor_kwargs["on_success"] = persist_success

            def reserve_model_call(estimated_cost_cny: float | None) -> None:
                generation_run_service.reserve_model_cost(
                    db,
                    run_id=claimed_run_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    estimated_cost_cny=estimated_cost_cny,
                    cost_limit_cny=settings.generation_task_cost_limit_cny,
                )

            def before_provider_call(provider_key: str):
                try:
                    return provider_circuit_service.acquire_provider_call(
                        db,
                        provider_key=provider_key,
                        cooldown_seconds=(
                            settings.provider_circuit_cooldown_seconds
                        ),
                        probe_lease_seconds=(
                            settings.provider_circuit_probe_lease_seconds
                        ),
                    )
                except provider_circuit_service.ProviderCircuitOpen as exc:
                    code = (
                        "provider_probe_in_progress"
                        if isinstance(
                            exc,
                            provider_circuit_service.ProviderProbeInProgress,
                        )
                        else "provider_circuit_open"
                    )
                    raise generation_run_service.GenerationProviderGuardError(
                        "模型供应商暂时不可用，需人工处理",
                        code=code,
                        provider_key=exc.provider_key,
                        circuit_state=exc.state,
                        consecutive_failures=exc.consecutive_failures,
                        retry_at=exc.retry_at,
                    ) from exc

            def record_provider_success(permit) -> None:
                provider_circuit_service.record_provider_success(
                    db,
                    permit=permit,
                )

            def record_provider_failure(permit, failure_code: str) -> None:
                state = provider_circuit_service.record_provider_failure(
                    db,
                    permit=permit,
                    failure_code=failure_code,
                    failure_threshold=(
                        settings.provider_circuit_failure_threshold
                    ),
                    cooldown_seconds=(
                        settings.provider_circuit_cooldown_seconds
                    ),
                )
                retry_at = (
                    state.cooldown_until if state.state == "open" else None
                )
                raise generation_run_service.GenerationProviderGuardError(
                    "模型供应商调用失败，已转人工处理",
                    code="provider_call_unavailable",
                    provider_key=permit.provider_key,
                    circuit_state=state.state,
                    consecutive_failures=state.consecutive_failures,
                    retry_at=retry_at,
                    failure_code=failure_code,
                )

            def release_provider_call(permit) -> None:
                provider_circuit_service.release_provider_call(
                    db,
                    permit=permit,
                )

            provider_hooks = llm_service.ProviderCallHooks(
                before_call=before_provider_call,
                record_success=record_provider_success,
                record_failure=record_provider_failure,
                release_call=release_provider_call,
            )
            with bind_request_id(run.request_id):
                with (
                    llm_service.model_cost_guard(reserve_model_call),
                    llm_service.provider_call_guard(provider_hooks),
                ):
                    response = selected_executor(db, **executor_kwargs)
            if finalized:
                db.commit()
            else:
                result_revision_id = getattr(response, "result_revision_id", None)
                if result_revision_id is None:
                    raise generation_output_service.GenerationOutputValidationError(
                        "方案生成成功响应缺少 revision"
                    )
                from app.services import generation_scene_service

                generation_scene_service.prepare_revision_scenes(
                    db,
                    revision_id=result_revision_id,
                )
                if not generation_run_service.mark_completed(
                    db,
                    run_id=claimed_run_id,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    generator=response.generator,
                    result_revision_id=result_revision_id,
                ):
                    raise generation_run_service.GenerationRunOwnershipError(
                        "方案生成结果提交前已失去租约"
                    )
        logger.info("方案生成完成: run_id=%s", claimed_run_id)
    except generation_output_service.GenerationOutputValidationError as exc:
        logger.error(
            "方案生成输出不可信: run_id=%s error=%s",
            claimed_run_id,
            exc,
        )
        with SessionLocal() as db:
            failed_run = db.get(GenerationRun, claimed_run_id)
            if failed_run is not None:
                generation_run_service.mark_failed(
                    db,
                    run=failed_run,
                    worker_id=worker_id,
                    worker_attempt=worker_attempt,
                    error_message=str(exc),
                    retryable=False,
                )
    except generation_run_service.GenerationProviderGuardError as exc:
        logger.warning(
            "方案生成被供应商熔断策略阻止: run_id=%s code=%s provider=%s",
            claimed_run_id,
            exc.code,
            exc.provider_key,
        )
        with SessionLocal() as db:
            blocked = generation_run_service.mark_provider_guard_blocked(
                db,
                run_id=claimed_run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error=exc,
            )
            if not blocked:
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
    except generation_run_service.GenerationCostGuardError as exc:
        logger.warning(
            "方案生成被成本策略阻止: run_id=%s code=%s",
            claimed_run_id,
            exc.code,
        )
        with SessionLocal() as db:
            blocked = generation_run_service.mark_cost_guard_blocked(
                db,
                run_id=claimed_run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error=exc,
            )
            if not blocked:
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
    except generation_run_service.GenerationBudgetReplanExhausted as exc:
        logger.warning(
            "方案生成预算重规划耗尽: run_id=%s budget_max=%s retry_count=%s",
            claimed_run_id,
            exc.budget_max,
            exc.retry_count,
        )
        with SessionLocal() as db:
            blocked = generation_run_service.mark_budget_replan_exhausted(
                db,
                run_id=claimed_run_id,
                worker_id=worker_id,
                worker_attempt=worker_attempt,
                error=exc,
            )
            if not blocked:
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
    configure_logging()

    while True:
        processed = process_one_run(worker_id=args.worker_id)
        if args.once:
            return 0
        if not processed:
            time.sleep(settings.generation_worker_poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
