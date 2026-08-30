from pathlib import Path


STARTUP_SCRIPT = Path(__file__).resolve().parents[3] / "startHaus.bat"
VITE_CONFIG = Path(__file__).resolve().parents[3] / "frontend" / "vite.config.ts"


def test_startup_script_discovers_python_without_machine_specific_path():
    script = STARTUP_SCRIPT.read_text(encoding="utf-8-sig")

    assert "D:\\software\\py314" not in script
    assert "HAUS_PYTHON" in script
    assert "py -3.14" in script
    assert "llm_key_configured" in script


def test_startup_script_uses_windows_line_endings_consistently():
    script_bytes = STARTUP_SCRIPT.read_bytes()

    assert b"\n" in script_bytes
    assert script_bytes.replace(b"\r\n", b"").find(b"\n") == -1


def test_startup_waits_for_backend_and_frontend_before_opening_browser():
    script = STARTUP_SCRIPT.read_text(encoding="utf-8-sig")

    assert 'call :wait_for_url "http://127.0.0.1:8081/health"' in script
    assert 'call :wait_for_url "http://localhost:8080/"' in script
    assert "timeout /t 5 >nul" not in script


def test_vite_proxy_uses_backend_ipv4_address():
    vite_config = VITE_CONFIG.read_text(encoding="utf-8")

    assert '"/api": "http://127.0.0.1:8081"' in vite_config
    assert '"/uploads": "http://127.0.0.1:8081"' in vite_config
