from pathlib import Path


def test_procfile_declares_api_and_all_required_workers_as_distinct_processes():
    root = Path(__file__).resolve().parents[2]
    lines = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in (root / "Procfile").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert set(lines) == {
        "release",
        "web",
        "worker-generation",
        "worker-effect-render",
        "worker-blender",
    }
    assert lines["release"] == "cd backend && python -m alembic upgrade head"
    assert "app.run_api" in lines["web"]
    assert "app.workers.generation_worker" in lines["worker-generation"]
    assert "app.workers.effect_render_worker" in lines["worker-effect-render"]
    assert "app.workers.blender_worker" in lines["worker-blender"]
