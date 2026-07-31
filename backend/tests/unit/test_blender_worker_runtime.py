from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.workers.blender_worker import (
    BlenderProcessError,
    execute_blender_process,
)


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
