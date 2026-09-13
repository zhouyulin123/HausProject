"""跨 Worker 尝试恢复不得重复发起可能已经计费的模型请求。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import DesignTask
from app.services import generation_run_service as service


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_cancel_after_reservation_still_wins(db):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    now = datetime.now(timezone.utc)
    service.create_run(db, task=task, max_attempts=3)
    run = service.claim_next_run(db, worker_id="worker-paid", lease_seconds=60,
                                execution_timeout_seconds=600, now=now)
    service.reserve_model_cost(db, run_id=run.id, worker_id="worker-paid", worker_attempt=1,
                               estimated_cost_cny=0.02, cost_limit_cny=1.0, now=now)
    service.request_cancel(db, run=run, now=now)
    service.recover_expired_runs(db, now=now + timedelta(seconds=61))
    db.refresh(run)
    assert run.status == "cancelled"


@pytest.mark.parametrize("estimated", [0.0, 0.02])
@pytest.mark.parametrize("failure", ["lease_expired", "executor_error", "legacy_queued"])
def test_reserved_call_stops_automatic_retry(db, estimated, failure):
    task = DesignTask(status="confirmed", progress=50)
    db.add(task)
    db.commit()
    now = datetime.now(timezone.utc)
    service.create_run(db, task=task, max_attempts=3)
    run = service.claim_next_run(db, worker_id="worker-paid", lease_seconds=60,
                                execution_timeout_seconds=600, now=now)
    service.reserve_model_cost(db, run_id=run.id, worker_id="worker-paid", worker_attempt=1,
                               estimated_cost_cny=estimated, cost_limit_cny=1.0, now=now)
    if failure == "lease_expired":
        service.recover_expired_runs(db, now=now + timedelta(seconds=61))
    elif failure == "executor_error":
        service.mark_failed(db, run=run, worker_id="worker-paid", worker_attempt=1,
                            error_message="模型已返回，后处理进程中断", retryable=True, now=now)
    else:
        # 模拟旧版本在已调用模型后留下的排队状态，升级后认领也必须拦截。
        run.status = "queued"
        run.worker_id = None
        run.next_retry_at = None
        db.commit()
        assert service.claim_next_run(db, worker_id="worker-upgraded", lease_seconds=60,
                                      now=now + timedelta(seconds=1)) is None
    db.refresh(run)
    assert run.status == "dead_letter"
    assert "自动重试" in run.error_message
    assert run.cost_reserved_cny == estimated
    assert service.claim_next_run(db, worker_id="worker-recovery", lease_seconds=60,
                                  now=now + timedelta(seconds=90)) is None
