from pathlib import Path
import os
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_SCRIPT = REPO_ROOT / "startHaus.bat"
VITE_CONFIG = REPO_ROOT / "frontend" / "vite.config.ts"
MANAGER_SCRIPT = REPO_ROOT / "manageHaus.ps1"


def test_startup_script_discovers_python_without_machine_specific_path():
    script = STARTUP_SCRIPT.read_text(encoding="utf-8-sig")

    assert "D:\\software\\py314" not in script
    assert "HAUS_PYTHON" in script
    assert "py -3.12" in script
    assert "py -3.14" in script
    assert "llm_key_configured" in script
    assert "app.db.schema_readiness" in script


def test_startup_script_uses_windows_line_endings_consistently():
    script_bytes = STARTUP_SCRIPT.read_bytes()

    assert b"\n" in script_bytes
    assert script_bytes.replace(b"\r\n", b"").find(b"\n") == -1


def test_startup_waits_for_backend_and_frontend_before_opening_browser():
    script = MANAGER_SCRIPT.read_text(encoding="utf-8-sig")

    browser = script.index("Start-Process 'http://127.0.0.1:8080'")
    assert script.index("Wait-HausUrl 'http://127.0.0.1:8081/ready' $created") < browser
    assert script.index("Wait-HausUrl 'http://127.0.0.1:8080/' $created") < browser
    assert '-WindowStyle Hidden' in script
    assert '--strictPort' in script


def run_powershell(script):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, timeout=30,
    )


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 后台进程生命周期")
def test_background_service_survives_launcher_exit_and_stops_its_children(tmp_path):
    runtime = tmp_path / "启动 日志"
    runtime.mkdir()
    setup = (
        f". '{str(MANAGER_SCRIPT).replace(chr(39), chr(39) * 2)}'; "
        f"$RuntimeDir = '{str(runtime).replace(chr(39), chr(39) * 2)}'; "
    )
    try:
        launch = run_powershell(setup + """
            $record = Start-HausService 'test-worker' $RuntimeDir 'ping.exe -n 120 127.0.0.1';
            Start-Sleep -Seconds 2;
            Assert-ServicesRunning @($record);
            $child = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($record.pid)" |
                Where-Object Name -eq 'ping.exe';
            if (-not $child) { throw '缺少测试子进程' };
            $child.ProcessId | Set-Content (Join-Path $RuntimeDir 'child.pid');
        """)
        assert launch.returncode == 0, launch.stderr
        verify = run_powershell(setup + """
            $record = @(Get-ServiceRecords)[0];
            Assert-ServicesRunning @($record);
            $wrong = [pscustomobject]@{pid=$record.pid; started='0'};
            if (Get-OwnedProcess $wrong) { throw '错误接受复用的 PID' };
            if (-not (Select-String -LiteralPath (Join-Path $RuntimeDir 'test-worker.stdout.log') -Pattern '127.0.0.1' -Quiet)) {
                throw '日志未写入文件';
            };
            $before = (Get-Item (Join-Path $RuntimeDir 'test-worker.stdout.log')).Length;
            Start-Sleep -Seconds 2;
            if ((Get-Item (Join-Path $RuntimeDir 'test-worker.stdout.log')).Length -le $before) {
                throw '启动器退出后日志停止写入';
            };
            Stop-HausService $record;
            Start-Sleep -Milliseconds 500;
            if (Get-OwnedProcess $record) { throw '父进程未停止' };
            $childId = [int](Get-Content (Join-Path $RuntimeDir 'child.pid'));
            if (Get-Process -Id $childId -ErrorAction SilentlyContinue) { throw '子进程未停止' };
            Stop-HausService $record;
        """)
        assert verify.returncode == 0, verify.stderr
    finally:
        run_powershell(setup + "Get-ServiceRecords | ForEach-Object { Stop-HausService $_ }")


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 启动互斥与失败处理")
def test_manager_rejects_concurrent_operations_and_dead_services(tmp_path):
    setup = (
        f". '{str(MANAGER_SCRIPT).replace(chr(39), chr(39) * 2)}'; "
        f"$RuntimeDir = '{str(tmp_path).replace(chr(39), chr(39) * 2)}'; "
    )
    result = run_powershell(setup + """
        $heldLock = [IO.File]::Open((Join-Path $RuntimeDir 'manager.lock'), 'OpenOrCreate', 'ReadWrite', 'None');
        try {
            $rejected = $false;
            try { Invoke-HausManager } catch { $rejected = $true };
            if (-not $rejected) { throw '并发操作未被拒绝' };
        } finally { $heldLock.Dispose() };
        $record = Start-HausService 'exited' $RuntimeDir 'exit /b 7';
        Start-Sleep -Seconds 1;
        $rejected = $false;
        try { Assert-ServicesRunning @($record) } catch { $rejected = $true };
        if (-not $rejected) { throw '退出进程被视为正常运行' };
        Stop-HausService $record;
    """)
    assert result.returncode == 0, result.stderr


def test_vite_proxy_uses_backend_ipv4_address():
    vite_config = VITE_CONFIG.read_text(encoding="utf-8")

    assert 'host: "127.0.0.1"' in vite_config
    assert 'process.env.HAUS_BACKEND_PORT || "8081"' in vite_config
    assert 'Number.isInteger(backendPort)' in vite_config
    assert 'backendPort < 1 || backendPort > 65535' in vite_config
    assert '"/api": `http://127.0.0.1:${backendPort}`' in vite_config
    assert '"/uploads": `http://127.0.0.1:${backendPort}`' in vite_config
