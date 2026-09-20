from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_local_launcher_starts_all_required_workers_after_schema_upgrade():
    launcher = Path("manageHaus.ps1").read_text(encoding="utf-8")

    api_start = launcher.index("-m app.run_api")
    migration = launcher.index("-m alembic upgrade head")
    assert migration < api_start
    assert launcher.count("-m alembic upgrade head") == 1
    for module in (
        "app.workers.generation_worker",
        "app.workers.effect_render_worker",
        "app.workers.blender_worker",
    ):
        assert f"$env:PYTHON_CMD -m {module}" in launcher
    assert "Name = 'frontend'" in launcher
    assert "Wait-HausUrl 'http://127.0.0.1:8081/ready' $created" in launcher
    assert "Wait-HausUrl 'http://127.0.0.1:8080/' $created" in launcher


def test_local_launcher_check_mode_does_not_start_services():
    launcher = Path("startHaus.bat").read_text(encoding="utf-8")
    check_guard = launcher.index('if /i "%~1"=="--check" goto check')
    first_start = launcher.index("-Action start")

    assert check_guard < first_start
    check_body = launcher[launcher.index("\n:check") :]
    assert "-Action start" not in check_body
