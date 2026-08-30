from pathlib import Path


STARTUP_SCRIPT = Path(__file__).resolve().parents[3] / "startHaus.bat"


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
