from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.workers.blender_worker import (
    BlenderProcessError,
    execute_blender_process,
    execute_supervised_blender_process,
)
from app.core.request_context import current_request_id


def test_worker_executes_static_command_without_shell_and_sanitizes_python_env(
    tmp_path,
):
    captured = {}
    output_path = tmp_path / "render.png"

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path.write_bytes(b"\x89PNG\r\n\x1a\nrender")
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    execute_blender_process(
        executable=Path("C:/Blender/blender.exe"),
        script_path=tmp_path / "trusted.py",
        manifest_path=tmp_path / "manifest.json",
        output_path=output_path,
        timeout_seconds=90,
        runner=runner,
        base_environment={
            "PATH": "safe",
            "PYTHONPATH": "attacker",
            "PYTHONHOME": "attacker",
        },
    )

    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == 90
    assert captured["kwargs"]["env"] == {"PATH": "safe"}
    assert "--disable-autoexec" in captured["command"]
    assert "--offline-mode" in captured["command"]


def test_worker_converts_nonzero_blender_exit_to_controlled_error(tmp_path):
    def runner(command, **kwargs):
        return CompletedProcess(
            command,
            70,
            stdout="",
            stderr="Python traceback with local paths",
        )

    with pytest.raises(BlenderProcessError, match="退出码 70"):
        execute_blender_process(
            executable=Path("C:/Blender/blender.exe"),
            script_path=tmp_path / "trusted.py",
            manifest_path=tmp_path / "manifest.json",
            output_path=tmp_path / "render.png",
            timeout_seconds=90,
            runner=runner,
            base_environment={},
        )


def test_supervised_worker_terminates_process_after_ownership_is_lost(tmp_path):
    class FakeProcess:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def communicate(self):
            return "", ""

    process = FakeProcess()
    with pytest.raises(BlenderProcessError, match="取消|租约"):
        execute_supervised_blender_process(
            executable=Path("C:/Blender/blender.exe"),
            script_path=tmp_path / "trusted.py",
            manifest_path=tmp_path / "manifest.json",
            output_path=tmp_path / "render.png",
            timeout_seconds=90,
            popen_factory=lambda *_, **__: process,
            should_continue=lambda: False,
            poll_seconds=0,
        )
    assert process.terminated is True


def test_blender_worker_binds_persisted_request_id_for_full_attempt(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    job = type(
        "Job",
        (),
        {"id": 7, "attempt": 1, "request_id": "blender-worker-trace-001"},
    )()
    monkeypatch.setattr("app.workers.blender_worker.SessionLocal", FakeSession)
    monkeypatch.setattr(
        "app.workers.blender_worker.blender_job_service.claim_next_job",
        lambda *_args, **_kwargs: job,
    )
    monkeypatch.setattr(
        "app.workers.blender_worker.blender_job_service.mark_failed",
        lambda *_args, **_kwargs: True,
    )

    def load_payload(_job_id):
        assert current_request_id() == "blender-worker-trace-001"
        raise ValueError("stop after context assertion")

    monkeypatch.setattr("app.workers.blender_worker._load_job_payload", load_payload)

    from app.workers import blender_worker

    assert blender_worker.process_one_job(
        worker_id="worker-a",
        executable=Path("C:/Blender/blender.exe"),
    )
    assert current_request_id() is None
