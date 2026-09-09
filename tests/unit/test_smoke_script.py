import pytest

from tests import smoke_test


def test_wait_for_generation_returns_completed_run(monkeypatch):
    monkeypatch.setattr(
        smoke_test,
        "get_json",
        lambda _path: {"status": "completed", "run_id": 9},
    )

    assert smoke_test.wait_for_generation(42, timeout_seconds=1) == {
        "status": "completed",
        "run_id": 9,
    }


def test_wait_for_generation_fails_on_terminal_worker_status(monkeypatch):
    monkeypatch.setattr(
        smoke_test,
        "get_json",
        lambda _path: {
            "status": "dead_letter",
            "error_message": "provider timeout",
        },
    )

    with pytest.raises(RuntimeError, match="dead_letter"):
        smoke_test.wait_for_generation(42, timeout_seconds=1)
