"""真实进程终止与 HTTP 请求边界验收；供应商、本地数据库均为隔离夹具。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import Base
from app.db.models import DesignTask, GenerationRun, ModelCallLedger
from app.services import generation_run_service


WORKER_CODE = """
from app.workers import generation_worker
from app.services import llm_service

def executor(db, *, task, on_step, on_meta, before_persist):
    llm_service._chat_json('返回 JSON', '隔离进程中断验收', max_tokens=20)
    raise AssertionError('阻塞供应商不应返回结果')

claimed = generation_worker.process_one_run(
    worker_id='isolated-crash-worker', executor=executor, start_heartbeat=False,
)
print('claimed=' + str(claimed), flush=True)
"""


@pytest.fixture(params=['sqlite', 'mysql'])
def isolated_database(request, tmp_path):
    if request.param == 'sqlite':
        yield 'sqlite+pysqlite:///' + (tmp_path / 'worker-crash.db').as_posix()
        return
    url = make_url(settings.database_url)
    if url.get_backend_name() != 'mysql':
        pytest.skip('未配置 MySQL，不能以 SQLite 代替 MySQL 进程故障验收')
    # 只操作此次生成的隔离库；不会把开发库中的任务交给故障 Worker。
    schema = 'test_worker_crash_' + uuid4().hex
    admin = create_engine(url.set(database=None))
    created = False
    try:
        try:
            with admin.begin() as connection:
                connection.execute(text(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4'))
                created = True
        except SQLAlchemyError as exc:
            pytest.skip('MySQL 隔离库不可创建：' + type(exc).__name__)
        yield url.set(database=schema).render_as_string(hide_password=False)
    finally:
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP DATABASE `{schema}`'))
        admin.dispose()


def test_killed_worker_does_not_resend_started_http_request(isolated_database):
    received = threading.Event()
    release = threading.Event()
    requests = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            requests.append(self.path)
            received.set()
            release.wait(60)
            self.close_connection = True

        def log_message(self, *_args):
            pass

    database_url = isolated_database
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        task = DesignTask(status='confirmed', progress=50)
        db.add(task)
        db.commit()
        run = generation_run_service.create_run(db, task=task, max_attempts=3)
        run_id = run.id

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, APP_ENV='test', DEVELOPMENT_CATALOG_ENABLED='false',
               DATABASE_URL=database_url, PYTHONPATH=str(root / 'backend'),
               LLM_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
               LLM_API_KEY='isolated-test-placeholder', LLM_MODEL='isolated-test-model',
               LLM_INPUT_PRICE_PER_MTOK='1', LLM_OUTPUT_PRICE_PER_MTOK='2',
               GENERATION_WORKER_LEASE_SECONDS='30',
               GENERATION_WORKER_EXECUTION_TIMEOUT_SECONDS='120')
    child = None
    try:
        child = subprocess.Popen([sys.executable, '-c', WORKER_CODE], cwd=root,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not received.wait(20):
            if child.poll() is None:
                child.kill()
            stdout, stderr = child.communicate(timeout=10)
            raise AssertionError('Worker 未到达本机供应商 HTTP 边界：' +
                                 (stdout + stderr).decode(errors='replace'))
        with Session(engine) as db:
            run = db.get(GenerationRun, run_id)
            assert run.status == 'running'
            original_cost = run.cost_reserved_cny
            assert original_cost > 0
            assert db.scalar(select(ModelCallLedger.status)) == 'reserved'
        # 真正结束子进程；不是抛异常或修改数据库时间来模拟崩溃。
        child.kill()
        child.wait(timeout=10)
        assert child.returncode != 0
        child.communicate(timeout=5)
        child = None
        time.sleep(31)  # 让真实三十秒租约过期，恢复仍使用系统当前时间。
        child = subprocess.Popen([sys.executable, '-c', WORKER_CODE], cwd=root,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr.decode(errors='replace')
        assert b'claimed=False' in stdout
        with Session(engine) as db:
            run = db.get(GenerationRun, run_id)
            assert run.status == 'dead_letter'
            assert run.attempt_count == 1
            assert run.next_retry_at is None
            assert run.cost_reserved_cny == original_cost
            assert db.scalar(select(ModelCallLedger.status)) == 'reserved'
        assert requests == ['/v1/chat/completions']
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
        release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        engine.dispose()
