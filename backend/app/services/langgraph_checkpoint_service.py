from __future__ import annotations

from collections.abc import Iterator, Sequence
from threading import RLock
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    DesignAgentTurn,
    LangGraphCheckpoint,
    LangGraphCheckpointWrite,
)


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver):
    """将单个 Agent turn 的 LangGraph superstep 独立持久化。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        task_id: int,
        turn_id: int,
    ) -> None:
        super().__init__()
        if task_id < 1 or turn_id < 1:
            raise ValueError("task_id 和 turn_id 必须为正整数")
        self._session_factory = session_factory
        self.task_id = task_id
        self.turn_id = turn_id
        self.thread_id = f"design-task:{task_id}"
        self.checkpoint_ns = f"turn:{turn_id}"
        # LangGraph 会从内部执行器并发调用 put 与 put_writes。
        self._write_lock = RLock()
        self._defer_persistence = False
        self._deferred_operations: list[tuple[str, Any]] = []

    def runnable_config(self) -> RunnableConfig:
        # LangGraph 顶层图保留空 namespace；持久层再映射到绑定的 turn namespace。
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "checkpoint_ns": "",
            }
        }

    def _scope(self, config: RunnableConfig) -> tuple[str, str, str]:
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id")
        if thread_id != self.thread_id:
            raise ValueError("checkpoint thread_id 与当前 DesignTask 不一致")
        runtime_ns = str(configurable.get("checkpoint_ns") or "")
        if runtime_ns not in {"", self.checkpoint_ns}:
            raise ValueError("checkpoint_ns 与当前 DesignAgentTurn 不一致")
        return thread_id, self.checkpoint_ns, runtime_ns

    def _assert_turn_binding(self, db: Session) -> None:
        turn_id = db.scalar(
            select(DesignAgentTurn.id).where(
                DesignAgentTurn.id == self.turn_id,
                DesignAgentTurn.task_id == self.task_id,
            )
        )
        if turn_id is None:
            raise ValueError("checkpoint 的 task_id 与 turn_id 绑定无效")

    def _tuple_from_row(
        self,
        db: Session,
        row: LangGraphCheckpoint,
        *,
        runtime_ns: str,
    ) -> CheckpointTuple:
        checkpoint = self.serde.loads_typed(
            (row.checkpoint_type, bytes(row.checkpoint_blob))
        )
        metadata = self.serde.loads_typed(
            (row.metadata_type, bytes(row.metadata_blob))
        )
        pending_rows = db.scalars(
            select(LangGraphCheckpointWrite)
            .where(
                LangGraphCheckpointWrite.task_id == self.task_id,
                LangGraphCheckpointWrite.turn_id == self.turn_id,
                LangGraphCheckpointWrite.thread_id == row.thread_id,
                LangGraphCheckpointWrite.checkpoint_ns == row.checkpoint_ns,
                LangGraphCheckpointWrite.checkpoint_id == row.checkpoint_id,
            )
            .order_by(
                LangGraphCheckpointWrite.writer_task_id,
                LangGraphCheckpointWrite.write_index,
            )
        ).all()
        writes = [
            (
                item.writer_task_id,
                item.channel,
                self.serde.loads_typed((item.value_type, bytes(item.value_blob))),
            )
            for item in pending_rows
        ]
        config: RunnableConfig = {
            "configurable": {
                "thread_id": row.thread_id,
                "checkpoint_ns": runtime_ns,
                "checkpoint_id": row.checkpoint_id,
            }
        }
        parent_config = None
        if row.parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": runtime_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=writes,
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, checkpoint_ns, runtime_ns = self._scope(config)
        checkpoint_id = get_checkpoint_id(config)
        with self._write_lock, self._session_factory() as db:
            statement = select(LangGraphCheckpoint).where(
                LangGraphCheckpoint.task_id == self.task_id,
                LangGraphCheckpoint.turn_id == self.turn_id,
                LangGraphCheckpoint.thread_id == thread_id,
                LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                statement = statement.where(
                    LangGraphCheckpoint.checkpoint_id == checkpoint_id
                )
            else:
                statement = statement.order_by(
                    LangGraphCheckpoint.checkpoint_id.desc()
                )
            row = db.scalars(statement).first()
            if row is None:
                return None
            return self._tuple_from_row(db, row, runtime_ns=runtime_ns)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if limit is not None and limit <= 0:
            return
        effective_config = config or self.runnable_config()
        thread_id, checkpoint_ns, runtime_ns = self._scope(effective_config)
        requested_id = get_checkpoint_id(effective_config)
        before_id = get_checkpoint_id(before) if before else None
        with self._write_lock, self._session_factory() as db:
            statement = select(LangGraphCheckpoint).where(
                LangGraphCheckpoint.task_id == self.task_id,
                LangGraphCheckpoint.turn_id == self.turn_id,
                LangGraphCheckpoint.thread_id == thread_id,
                LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if requested_id:
                statement = statement.where(
                    LangGraphCheckpoint.checkpoint_id == requested_id
                )
            if before_id:
                statement = statement.where(
                    LangGraphCheckpoint.checkpoint_id < before_id
                )
            rows = db.scalars(
                statement.order_by(LangGraphCheckpoint.checkpoint_id.desc())
            ).all()
            emitted = 0
            for row in rows:
                item = self._tuple_from_row(db, row, runtime_ns=runtime_ns)
                if filter and not all(
                    item.metadata.get(key) == value for key, value in filter.items()
                ):
                    continue
                yield item
                emitted += 1
                if limit is not None and emitted >= limit:
                    break

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions  # 完整快照包含 channel_values 与 channel_versions。
        thread_id, checkpoint_ns, runtime_ns = self._scope(config)
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        parent_checkpoint_id = (config.get("configurable") or {}).get(
            "checkpoint_id"
        )
        values = {
            "task_id": self.task_id,
            "turn_id": self.turn_id,
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint["id"],
            "parent_checkpoint_id": parent_checkpoint_id,
            "checkpoint_type": checkpoint_type,
            "checkpoint_blob": checkpoint_blob,
            "metadata_type": metadata_type,
            "metadata_blob": metadata_blob,
        }
        with self._write_lock:
            if self._defer_persistence:
                self._deferred_operations.append(("checkpoint", values))
            else:
                self._store_checkpoint(values)
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": runtime_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def _store_checkpoint(self, values: dict[str, Any]) -> None:
        with self._session_factory() as db:
            self._assert_turn_binding(db)
            existing = db.scalar(
                select(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == values["thread_id"],
                    LangGraphCheckpoint.checkpoint_ns == values["checkpoint_ns"],
                    LangGraphCheckpoint.checkpoint_id == values["checkpoint_id"],
                )
            )
            if existing is None:
                db.add(LangGraphCheckpoint(**values))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    existing = db.scalar(
                        select(LangGraphCheckpoint).where(
                            LangGraphCheckpoint.thread_id == values["thread_id"],
                            LangGraphCheckpoint.checkpoint_ns
                            == values["checkpoint_ns"],
                            LangGraphCheckpoint.checkpoint_id
                            == values["checkpoint_id"],
                        )
                    )
                    if existing is None:
                        raise
            if existing is not None and (
                bytes(existing.checkpoint_blob) != values["checkpoint_blob"]
                or bytes(existing.metadata_blob) != values["metadata_blob"]
                or existing.parent_checkpoint_id != values["parent_checkpoint_id"]
            ):
                raise ValueError("同一 checkpoint_id 的持久化内容发生漂移")

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, checkpoint_ns, _ = self._scope(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            raise ValueError("pending writes 缺少 checkpoint_id")
        records = []
        for index, (channel, value) in enumerate(writes):
            value_type, value_blob = self.serde.dumps_typed(value)
            records.append(
                {
                    "task_id": self.task_id,
                    "turn_id": self.turn_id,
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "writer_task_id": task_id,
                    "task_path": task_path,
                    "write_index": WRITES_IDX_MAP.get(channel, index),
                    "channel": channel,
                    "value_type": value_type,
                    "value_blob": value_blob,
                }
            )
        with self._write_lock:
            if self._defer_persistence:
                self._deferred_operations.append(("writes", records))
            else:
                self._store_writes(records)

    def _store_writes(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        with self._session_factory() as db:
            self._assert_turn_binding(db)
            for record in records:
                existing = db.scalar(
                    select(LangGraphCheckpointWrite).where(
                        LangGraphCheckpointWrite.task_id == self.task_id,
                        LangGraphCheckpointWrite.turn_id == self.turn_id,
                        LangGraphCheckpointWrite.thread_id == record["thread_id"],
                        LangGraphCheckpointWrite.checkpoint_ns
                        == record["checkpoint_ns"],
                        LangGraphCheckpointWrite.checkpoint_id
                        == record["checkpoint_id"],
                        LangGraphCheckpointWrite.writer_task_id
                        == record["writer_task_id"],
                        LangGraphCheckpointWrite.write_index
                        == record["write_index"],
                    )
                )
                if existing is not None and record["write_index"] >= 0:
                    continue
                if existing is not None:
                    existing.channel = record["channel"]
                    existing.value_type = record["value_type"]
                    existing.value_blob = record["value_blob"]
                    existing.task_path = record["task_path"]
                else:
                    db.add(LangGraphCheckpointWrite(**record))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # 并发重放只可能命中同一唯一键；已存在写入即视为幂等成功。
                for record in records:
                    persisted = db.scalar(
                        select(LangGraphCheckpointWrite.id).where(
                            LangGraphCheckpointWrite.task_id == self.task_id,
                            LangGraphCheckpointWrite.turn_id == self.turn_id,
                            LangGraphCheckpointWrite.thread_id
                            == record["thread_id"],
                            LangGraphCheckpointWrite.checkpoint_ns
                            == record["checkpoint_ns"],
                            LangGraphCheckpointWrite.checkpoint_id
                            == record["checkpoint_id"],
                            LangGraphCheckpointWrite.writer_task_id
                            == record["writer_task_id"],
                            LangGraphCheckpointWrite.write_index
                            == record["write_index"],
                        )
                    )
                    if persisted is None:
                        raise

    def defer(self) -> None:
        """业务工具产生未提交写入后，暂存后续图检查点直到业务提交。"""
        with self._write_lock:
            self._defer_persistence = True

    def flush_deferred(self) -> None:
        with self._write_lock:
            operations = self._deferred_operations
            self._deferred_operations = []
            self._defer_persistence = False
            for index, (kind, payload) in enumerate(operations):
                try:
                    if kind == "checkpoint":
                        self._store_checkpoint(payload)
                    else:
                        self._store_writes(payload)
                except Exception:
                    self._deferred_operations = operations[index:]
                    self._defer_persistence = True
                    raise

    def delete_thread(self, thread_id: str) -> None:
        if thread_id != self.thread_id:
            raise ValueError("checkpoint thread_id 与当前 DesignTask 不一致")
        with self._write_lock, self._session_factory() as db:
            db.execute(
                delete(LangGraphCheckpointWrite).where(
                    LangGraphCheckpointWrite.task_id == self.task_id,
                    LangGraphCheckpointWrite.thread_id == thread_id,
                )
            )
            db.execute(
                delete(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.task_id == self.task_id,
                    LangGraphCheckpoint.thread_id == thread_id,
                )
            )
            db.commit()

    def has_checkpoint(self) -> bool:
        return self.get_tuple(self.runnable_config()) is not None
