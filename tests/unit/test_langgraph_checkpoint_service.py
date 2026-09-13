from __future__ import annotations

from pathlib import Path
from threading import Barrier, Thread
import pytest
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from typing_extensions import TypedDict

from app.db.database import Base
from app.db.models import (
    DesignAgentTurn,
    DesignTask,
    LangGraphCheckpoint,
    LangGraphCheckpointWrite,
)
from app.services.langgraph_checkpoint_service import SqlAlchemyCheckpointSaver


class CounterState(TypedDict):
    value: int


@pytest.fixture
def checkpoint_context():
    artifacts_dir = Path(__file__).resolve().parents[2] / ".test_artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    database_path = artifacts_dir / "langgraph-checkpoints-unit.db"
    database_path.unlink(missing_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        task = DesignTask(status="waiting_input", raw_user_input="测试检查点")
        db.add(task)
        db.flush()
        turns = [
            DesignAgentTurn(
                task_id=task.id,
                client_turn_id=f"checkpoint-turn-{index}",
                active_mode="catalog_design",
                intent="design",
                status="running",
                request_json={"message": "继续设计"},
            )
            for index in (1, 2)
        ]
        db.add_all(turns)
        db.commit()
        task_id = task.id
        turn_ids = [turn.id for turn in turns]
    try:
        yield factory, task_id, turn_ids
    finally:
        engine.dispose()
        database_path.unlink(missing_ok=True)


def _counter_graph(saver: SqlAlchemyCheckpointSaver):
    graph = StateGraph(CounterState)
    graph.add_node("increment", lambda state: {"value": state["value"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    return graph.compile(checkpointer=saver)


def test_saver_persists_supersteps_and_supports_get_list_delete(checkpoint_context):
    factory, task_id, turn_ids = checkpoint_context
    saver = SqlAlchemyCheckpointSaver(
        factory,
        task_id=task_id,
        turn_id=turn_ids[0],
    )
    graph = _counter_graph(saver)

    assert graph.invoke({"value": 1}, saver.runnable_config()) == {"value": 2}

    checkpoints = list(saver.list(saver.runnable_config()))
    assert len(checkpoints) >= 3
    assert checkpoints[0].checkpoint["channel_values"]["value"] == 2
    assert checkpoints[0].metadata["source"] == "loop"
    assert any(item.metadata["source"] == "input" for item in checkpoints)
    assert any(item.pending_writes for item in checkpoints[1:])

    latest = saver.get_tuple(saver.runnable_config())
    assert latest is not None
    exact = saver.get_tuple(latest.config)
    assert exact is not None
    assert exact.checkpoint["id"] == latest.checkpoint["id"]
    older = list(
        saver.list(
            saver.runnable_config(),
            before=latest.config,
            filter={"source": "loop"},
            limit=1,
        )
    )
    assert len(older) == 1
    assert older[0].checkpoint["id"] != latest.checkpoint["id"]

    with factory() as db:
        rows = db.scalars(
            select(LangGraphCheckpoint).where(
                LangGraphCheckpoint.task_id == task_id,
                LangGraphCheckpoint.turn_id == turn_ids[0],
            )
        ).all()
        assert rows
        assert {row.thread_id for row in rows} == {f"design-task:{task_id}"}
        assert {row.checkpoint_ns for row in rows} == {f"turn:{turn_ids[0]}"}
        assert all(row.checkpoint_blob and row.metadata_blob for row in rows)

    saver.delete_thread(f"design-task:{task_id}")
    assert list(saver.list(saver.runnable_config())) == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LangGraphCheckpoint)) == 0
        assert db.scalar(select(func.count()).select_from(LangGraphCheckpointWrite)) == 0


def test_turn_namespaces_do_not_read_each_others_state(checkpoint_context):
    factory, task_id, turn_ids = checkpoint_context
    first = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_ids[0])
    second = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_ids[1])

    assert _counter_graph(first).invoke({"value": 4}, first.runnable_config()) == {
        "value": 5
    }
    assert second.get_tuple(second.runnable_config()) is None
    assert _counter_graph(second).invoke({"value": 9}, second.runnable_config()) == {
        "value": 10
    }
    assert first.get_tuple(first.runnable_config()).checkpoint["channel_values"][
        "value"
    ] == 5
    assert second.get_tuple(second.runnable_config()).checkpoint["channel_values"][
        "value"
    ] == 10


def test_pending_writes_are_idempotent_under_concurrent_replay(checkpoint_context):
    factory, task_id, turn_ids = checkpoint_context
    saver = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_ids[0])
    graph = _counter_graph(saver)
    graph.invoke({"value": 1}, saver.runnable_config())
    latest = saver.get_tuple(saver.runnable_config())
    config = latest.config
    barrier = Barrier(2)
    errors: list[Exception] = []

    def write_once() -> None:
        try:
            barrier.wait(timeout=5)
            saver.put_writes(config, [("result", {"ok": True})], "same-node")
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [Thread(target=write_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    replayed = saver.get_tuple(config)
    matching = [
        write
        for write in replayed.pending_writes
        if write[0] == "same-node" and write[1] == "result"
    ]
    assert matching == [("same-node", "result", {"ok": True})]


def test_saver_rejects_cross_task_thread_scope(checkpoint_context):
    factory, task_id, turn_ids = checkpoint_context
    saver = SqlAlchemyCheckpointSaver(factory, task_id=task_id, turn_id=turn_ids[0])
    with pytest.raises(ValueError, match="thread_id"):
        saver.get_tuple(
            {"configurable": {"thread_id": "design-task:999", "checkpoint_ns": ""}}
        )
