from __future__ import annotations

from app import run_api


def test_api_entrypoint_uses_json_logging_and_single_access_event(monkeypatch):
    configured: list[bool] = []
    uvicorn_calls: list[dict] = []
    monkeypatch.setattr(run_api, "configure_logging", lambda: configured.append(True))
    monkeypatch.setattr(
        run_api.uvicorn,
        "run",
        lambda *args, **kwargs: uvicorn_calls.append(
            {"args": args, "kwargs": kwargs}
        ),
    )

    assert run_api.main(["--host", "127.0.0.1", "--port", "8099"]) == 0
    assert configured == [True]
    assert uvicorn_calls == [
        {
            "args": ("app.main:app",),
            "kwargs": {
                "host": "127.0.0.1",
                "port": 8099,
                "access_log": False,
                "log_config": None,
            },
        }
    ]
