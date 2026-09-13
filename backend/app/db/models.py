from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.mysql import MEDIUMBLOB

from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    openid = Column(String(100), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    nickname = Column(String(50), nullable=True)
    avatar = Column(String(255), nullable=True)
    # customer / factory / admin：普通用户 / 厂家 / 管理员
    role = Column(String(20), nullable=False, default="customer", index=True)
    phone_verified = Column(Boolean, nullable=False, default=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserProfile(Base):
    """用户的长期装修画像：跨会话、跨设备记忆其偏好。"""

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    # 关键维度用列，便于确定性查询（如预算内推荐）
    budget_min = Column(Integer, nullable=True)
    budget_max = Column(Integer, nullable=True)
    preferred_styles = Column(JSON, nullable=False, default=list)
    # 扩展维度用 JSON 兜底，避免频繁迁移
    profile_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("User", back_populates="profile")


class DesignTask(Base):
    __tablename__ = "design_tasks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    # pending / analyzing / waiting_confirm / confirmed / generating / completed / failed
    status = Column(String(50), default="pending", index=True)
    progress = Column(Integer, default=0)
    raw_user_input = Column(Text, nullable=True)
    confirmed_requirement_json = Column(JSON, nullable=True)
    space_type = Column(String(50), nullable=True)
    style = Column(String(50), nullable=True)
    budget_min = Column(Integer, nullable=True)
    budget_max = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    agent_state_json = Column(JSON, nullable=True)
    agent_state_version = Column(Integer, nullable=False, default=0)
    active_mode = Column(
        String(30), nullable=False, default="catalog_design", index=True
    )


class UploadedImage(Base):
    __tablename__ = "uploaded_images"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True)
    image_type = Column(
        String(50), default="room_photo"
    )  # room_photo / floor_plan / reference_image
    file_url = Column(String(255))
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    content_digest = Column(String(71), nullable=True)
    analysis_json = Column(JSON, nullable=True)  # AI 空间识别结果
    # 上传分析成功时写入一次；用户校准仅更新 analysis_json 投影。
    original_prediction_json = Column(JSON, nullable=True)
    original_prediction_source = Column(String(30), nullable=True)
    original_prediction_model = Column(String(100), nullable=True)
    original_prediction_digest = Column(String(71), nullable=True)
    analysis_model_call_attempted = Column(Boolean, nullable=False, default=False)
    analysis_billing_status = Column(
        String(20), nullable=False, default="not_billable"
    )
    analysis_cost_cny = Column(Float, nullable=True)
    upload_operation_key = Column(
        String(71), nullable=True, unique=True, index=True
    )
    upload_request_digest = Column(String(71), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RoomFactConfirmation(Base):
    """空间事实的追加式用户确认记录，保留原图、原值与确认者。"""

    __tablename__ = "room_fact_confirmations"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        Integer,
        ForeignKey("uploaded_images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    fact_path = Column(String(255), nullable=False, index=True)
    previous_value_json = Column(JSON, nullable=True)
    confirmed_value_json = Column(JSON, nullable=False)
    previous_confidence = Column(Float, nullable=True)
    confirmed_by_type = Column(String(30), nullable=False)
    confirmed_by_id = Column(String(100), nullable=False, index=True)
    confirmed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class RequirementParseResult(Base):
    __tablename__ = "requirement_parse_results"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), index=True)
    raw_input = Column(Text)
    parsed_json = Column(JSON)
    missing_fields = Column(JSON, nullable=True)
    follow_up_questions = Column(JSON, nullable=True)
    parser = Column(String(20), default="rule")  # llm / rule
    parser_model = Column(String(100), nullable=True)
    model_call_attempted = Column(Boolean, nullable=False, default=False)
    billing_status = Column(String(20), nullable=False, default="not_billable")
    cost_cny = Column(Float, nullable=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DesignResult(Base):
    __tablename__ = "design_results"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), index=True)
    plans_json = Column(JSON)  # 3 套方案（与前端 DesignPlan 结构对齐）
    quote_json = Column(JSON, nullable=True)
    report_json = Column(JSON, nullable=True)
    generator = Column(String(20), default="template")  # llm / template
    pdf_url = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChatLog(Base):
    __tablename__ = "chat_logs"
    id = Column(Integer, primary_key=True, index=True)
    # 兼容历史孤立记录；应用层所有新写入必须提供 task_id。
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True, index=True)
    role = Column(String(10))  # user / ai
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DesignAgentTurn(Base):
    """客户端幂等键绑定的一轮智能体请求与最终响应。"""

    __tablename__ = "design_agent_turns"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "client_turn_id",
            name="uq_design_agent_turns_task_client_turn",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_turn_id = Column(String(100), nullable=False)
    active_mode = Column(String(30), nullable=False)
    intent = Column(String(50), nullable=False, default="unknown")
    status = Column(String(30), nullable=False, default="running", index=True)
    request_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AgentApproval(Base):
    """Agent 转人工后的持久化审批请求与最终决定。"""

    __tablename__ = "agent_approvals"
    __table_args__ = (
        UniqueConstraint(
            "turn_id",
            "approval_type",
            name="uq_agent_approvals_turn_type",
        ),
        UniqueConstraint(
            "task_id",
            "client_decision_id",
            name="uq_agent_approvals_task_client_decision",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        Integer,
        ForeignKey("design_agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approval_type = Column(String(40), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    request_reason = Column(Text, nullable=False)
    reason_code = Column(String(100), nullable=False, index=True)
    request_context_json = Column(JSON, nullable=False, default=dict)
    requested_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    client_decision_id = Column(String(100), nullable=True)
    decision = Column(String(20), nullable=True)
    conclusion = Column(Text, nullable=True)
    decided_by_type = Column(String(30), nullable=True)
    decided_by_id = Column(String(100), nullable=True, index=True)
    decided_at = Column(DateTime(timezone=True), nullable=True, index=True)


class LangGraphCheckpoint(Base):
    """绑定 DesignTask 与单轮 turn 的 LangGraph 完整 superstep 快照。"""

    __tablename__ = "langgraph_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            name="uq_langgraph_checkpoint_scope_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        Integer,
        ForeignKey("design_agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(String(191), nullable=False, index=True)
    checkpoint_ns = Column(String(191), nullable=False, index=True)
    checkpoint_id = Column(String(64), nullable=False)
    parent_checkpoint_id = Column(String(64), nullable=True)
    checkpoint_type = Column(String(32), nullable=False)
    checkpoint_blob = Column(
        LargeBinary().with_variant(MEDIUMBLOB(), "mysql"),
        nullable=False,
    )
    metadata_type = Column(String(32), nullable=False)
    metadata_blob = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LangGraphCheckpointWrite(Base):
    """节点完成后、下一 superstep 提交前的可恢复 channel writes。"""

    __tablename__ = "langgraph_checkpoint_writes"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "writer_task_id",
            "write_index",
            name="uq_langgraph_checkpoint_write_task_index",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        Integer,
        ForeignKey("design_agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(String(191), nullable=False, index=True)
    checkpoint_ns = Column(String(191), nullable=False, index=True)
    checkpoint_id = Column(String(64), nullable=False)
    writer_task_id = Column(String(191), nullable=False)
    task_path = Column(String(500), nullable=False, default="")
    write_index = Column(Integer, nullable=False)
    channel = Column(String(191), nullable=False)
    value_type = Column(String(32), nullable=False)
    value_blob = Column(
        LargeBinary().with_variant(MEDIUMBLOB(), "mysql"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CustomFurnitureDraftMutation(Base):
    """与真实 Agent turn 隔离的定制家具草稿幂等记录。"""

    __tablename__ = "custom_furniture_draft_mutations"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "client_mutation_id",
            name="uq_custom_draft_mutations_task_client_mutation",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_mutation_id = Column(String(100), nullable=False)
    request_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OpenGeometryRateLimitBucket(Base):
    """跨 API 进程共享的开放几何滑动窗口状态。"""

    __tablename__ = "open_geometry_rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "task_id",
            name="uq_open_geometry_rate_limit_scope",
        ),
        CheckConstraint(
            "record_version > 0",
            name="ck_open_geometry_rate_limit_record_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        String(36),
        ForeignKey("anonymous_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempted_at_json = Column(JSON, nullable=False, default=list)
    record_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DesignAgentEvent(Base):
    """不含思维链的可审计 Agent 工具与状态事件。"""

    __tablename__ = "design_agent_events"
    __table_args__ = (
        UniqueConstraint(
            "turn_id",
            "sequence",
            name="uq_design_agent_events_turn_sequence",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(
        Integer,
        ForeignKey("design_agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(30), nullable=False)
    node = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False)
    source = Column(String(30), nullable=False)
    summary = Column(String(500), nullable=False)
    details_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TaskExecutionEvent(Base):
    """跨 Agent 与异步作业的安全、追加式任务时间线投影。"""

    __tablename__ = "task_execution_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_task_execution_events_event_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(20), nullable=False, index=True)
    source_id = Column(Integer, nullable=False)
    attempt = Column(Integer, nullable=True)
    event_code = Column(String(50), nullable=False, index=True)
    billing_status = Column(String(20), nullable=False, index=True)
    cost_cny = Column(Float, nullable=True)
    event_key = Column(String(150), nullable=False)
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class ModelCallCostAccount(Base):
    """模型调用成本聚合根；同一任务或会话只允许一个冻结上限。"""

    __tablename__ = "model_call_cost_accounts"
    __table_args__ = (
        UniqueConstraint(
            "scope_kind",
            "scope_id",
            name="uq_model_call_cost_accounts_scope",
        ),
        CheckConstraint(
            "scope_kind IN ('task', 'session')",
            name="ck_model_call_cost_account_scope_kind",
        ),
        CheckConstraint(
            "cost_limit_cny > 0",
            name="ck_model_call_cost_account_limit",
        ),
        CheckConstraint(
            "allocated_cost_cny >= 0 AND actual_cost_cny >= 0",
            name="ck_model_call_cost_account_costs",
        ),
        CheckConstraint(
            "unknown_cost_call_count >= 0",
            name="ck_model_call_cost_account_unknown_count",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope_kind = Column(String(20), nullable=False, index=True)
    scope_id = Column(String(100), nullable=False, index=True)
    task_id = Column(
        Integer,
        nullable=True,
        index=True,
    )
    cost_limit_cny = Column(Numeric(18, 6), nullable=False)
    allocated_cost_cny = Column(
        Numeric(18, 6), nullable=False, default=0.0, server_default="0"
    )
    actual_cost_cny = Column(
        Numeric(18, 6), nullable=False, default=0.0, server_default="0"
    )
    unknown_cost_call_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelCallLedger(Base):
    """逐次模型供应商调用账本，不保存 Prompt、图片或用户输入。"""

    __tablename__ = "model_call_ledgers"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "operation_key",
            "call_index",
            name="uq_model_call_ledgers_operation_call",
        ),
        CheckConstraint(
            "status IN ('reserved', 'succeeded', 'failed', 'blocked')",
            name="ck_model_call_ledger_status",
        ),
        CheckConstraint(
            "modality IN ('text', 'vision')",
            name="ck_model_call_ledger_modality",
        ),
        CheckConstraint(
            "estimated_cost_cny IS NULL OR estimated_cost_cny >= 0",
            name="ck_model_call_ledger_estimated_cost",
        ),
        CheckConstraint(
            "actual_cost_cny IS NULL OR actual_cost_cny >= 0",
            name="ck_model_call_ledger_actual_cost",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(
        Integer,
        ForeignKey("model_call_cost_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        Integer,
        nullable=True,
        index=True,
    )
    request_id = Column(String(100), nullable=True, index=True)
    operation_key = Column(String(150), nullable=False)
    call_index = Column(Integer, nullable=False)
    provider_key = Column(String(100), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    modality = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, index=True)
    estimated_cost_cny = Column(Numeric(18, 6), nullable=True)
    actual_cost_cny = Column(Numeric(18, 6), nullable=True)
    billing_status = Column(String(20), nullable=False, default="not_billable")
    usage_json = Column(JSON, nullable=False, default=dict)
    failure_code = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class DesignFeedbackEvent(Base):
    """用户对方案与场景的结构化行为，用于真实质量反馈闭环。"""

    __tablename__ = "design_feedback_events"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "client_event_id",
            name="uq_design_feedback_task_client_event",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_event_id = Column(String(100), nullable=False)
    action_type = Column(String(30), nullable=False, index=True)
    payload_hash = Column(String(64), nullable=False)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scene_id = Column(
        Integer,
        ForeignKey("design_scenes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scene_version = Column(Integer, nullable=True)
    room_id = Column(String(100), nullable=True)
    instance_id = Column(String(100), nullable=True)
    source_sku = Column(String(50), nullable=True, index=True)
    target_sku = Column(String(50), nullable=True, index=True)
    satisfaction_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FailureCluster(Base):
    """不含案例或用户内容的匿名失败聚类及修复生命周期。"""

    __tablename__ = "failure_clusters"

    id = Column(Integer, primary_key=True, index=True)
    fingerprint = Column(String(64), nullable=False, unique=True, index=True)
    taxonomy_version = Column(String(100), nullable=False)
    data_version = Column(String(100), nullable=False)
    failure_type = Column(String(50), nullable=False, index=True)
    code = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    owner = Column(String(100), nullable=True, index=True)
    record_version = Column(Integer, nullable=False, default=1)
    occurrence_count = Column(Integer, nullable=False, default=0)
    affected_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, index=True)
    detected_version = Column(String(100), nullable=False)
    fixed_version = Column(String(100), nullable=True)
    verified_version = Column(String(100), nullable=True)
    verification_report_id = Column(
        String(100),
        ForeignKey("failure_verification_imports.report_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    report_digest = Column(String(71), nullable=True)
    coverage_digest = Column(String(71), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class FailureTriageImport(Base):
    """已同步报告的幂等凭据；仅保存报告标识与内容哈希。"""

    __tablename__ = "failure_triage_imports"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String(100), nullable=False, unique=True, index=True)
    payload_hash = Column(String(64), nullable=False)
    semantic_hash = Column(String(64), nullable=False, unique=True, index=True)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())


class FailureVerificationImport(Base):
    """已验签复测证明的幂等与覆盖凭据。"""

    __tablename__ = "failure_verification_imports"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String(100), nullable=False, unique=True, index=True)
    report_digest = Column(String(71), nullable=False)
    semantic_digest = Column(String(71), nullable=False, unique=True, index=True)
    coverage_digest = Column(String(71), nullable=False)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())


class RealWorldCaseRecord(Base):
    """从既有设计任务提升的真实案例治理记录。"""

    __tablename__ = "real_world_case_records"
    __table_args__ = (
        CheckConstraint(
            "origin = 'private_real'",
            name="ck_real_world_case_origin_private",
        ),
        CheckConstraint(
            "split IN ('unassigned', 'development', 'regression', 'blind')",
            name="ck_real_world_case_split",
        ),
        CheckConstraint(
            "redaction_review IN ('pending', 'reviewed', 'rejected')",
            name="ck_real_world_case_redaction",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_ref = Column(String(40), nullable=False, unique=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    uploaded_image_id = Column(
        Integer,
        ForeignKey("uploaded_images.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    origin = Column(
        String(20), nullable=False, default="private_real", server_default="private_real"
    )
    asset_digest = Column(String(71), nullable=False, unique=True, index=True)
    task_input_json = Column(JSON, nullable=False)
    task_input_digest = Column(String(71), nullable=False)
    split = Column(
        String(20), nullable=False, default="unassigned", server_default="unassigned"
    )
    redaction_review = Column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    record_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RealWorldCaseImport(Base):
    """真实案例提升操作的幂等凭据。"""

    __tablename__ = "real_world_case_imports"

    id = Column(Integer, primary_key=True, index=True)
    client_import_id = Column(String(100), nullable=False, unique=True, index=True)
    request_digest = Column(String(71), nullable=False)
    case_id = Column(
        Integer,
        ForeignKey("real_world_case_records.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RealWorldConsentDecision(Base):
    """真实案例授权的追加式决定，不保存授权文书内容。"""

    __tablename__ = "real_world_consent_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('granted', 'denied', 'revoked')",
            name="ck_real_world_consent_decision",
        ),
        CheckConstraint(
            "legal_basis IN ('explicit_consent', 'contract', 'withdrawal_request')",
            name="ck_real_world_consent_legal_basis",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(
        Integer,
        ForeignKey("real_world_case_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    decision = Column(String(20), nullable=False, index=True)
    legal_basis = Column(String(30), nullable=False)
    allowed_purposes_json = Column(JSON, nullable=False)
    evidence_digest = Column(String(71), nullable=True)
    effective_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RealWorldAnnotationRevision(Base):
    """经过严格 Schema 校验并与来源资产绑定的标注修订。"""

    __tablename__ = "real_world_annotation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "annotation_digest",
            name="uq_real_world_annotation_case_digest",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(
        Integer,
        ForeignKey("real_world_case_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    label_version = Column(String(100), nullable=False)
    annotation_json = Column(JSON, nullable=False)
    annotation_digest = Column(String(71), nullable=False, index=True)
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RealWorldDatasetRevision(Base):
    """不可变的真实案例数据集冻结快照。"""

    __tablename__ = "real_world_dataset_revisions"

    id = Column(Integer, primary_key=True, index=True)
    revision_ref = Column(String(40), nullable=False, unique=True, index=True)
    schema_version = Column(String(10), nullable=False)
    dataset_version = Column(String(100), nullable=False, unique=True, index=True)
    manifest_digest = Column(String(71), nullable=False, unique=True, index=True)
    snapshot_json = Column(JSON, nullable=False)
    case_count = Column(Integer, nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GovernanceEvent(Base):
    """不含案例内容的真实案例治理追加式审计事件。"""

    __tablename__ = "real_world_governance_events"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(
        Integer,
        ForeignKey("real_world_case_records.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action = Column(String(50), nullable=False, index=True)
    request_id = Column(String(100), nullable=False, index=True)
    before_digest = Column(String(71), nullable=False)
    after_digest = Column(String(71), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ShopSetting(Base):
    """店铺信息（单行，id=1）：用于提案 PDF 页头/页脚与前端展示。"""

    __tablename__ = "shop_settings"
    id = Column(Integer, primary_key=True)
    shop_name = Column(String(100), nullable=False, default="")
    phone = Column(String(50), nullable=True)
    wechat = Column(String(50), nullable=True)
    address = Column(String(200), nullable=True)
    slogan = Column(String(200), nullable=True)
    logo_url = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Customer(Base):
    """客户跟单记录（店内轻 CRM）。"""

    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    phone = Column(String(20), nullable=True, index=True)
    wechat = Column(String(50), nullable=True)
    address = Column(String(200), nullable=True)
    note = Column(Text, nullable=True)  # 跟单备注
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Product(Base):
    """成品家具 SKU（自家商品库）。"""

    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(50), unique=True, index=True, nullable=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), index=True)  # 沙发 / 床 / 餐桌 / 柜子 / 灯具 ...
    room = Column(String(50), index=True)  # 客厅 / 卧室 / 餐厅 / 书房
    style = Column(String(50), index=True)  # 奶油风 / 原木风 / 现代简约 ...
    material = Column(String(100), nullable=True)
    price = Column(Integer, nullable=False)  # 单件价格（元）
    price_max = Column(Integer, nullable=True)  # 区间上限（可选，如带选配）
    size = Column(String(100), nullable=True)  # 尺寸描述
    selling_point = Column(Text, nullable=True)  # 卖点 / 推荐语
    alternative = Column(String(200), nullable=True)  # 替代选择说明
    image_url = Column(String(255), nullable=True)
    model_url = Column(String(255), nullable=True)
    model_status = Column(String(20), nullable=False, default="missing")
    model_width_mm = Column(Integer, nullable=True)
    model_height_mm = Column(Integer, nullable=True)
    model_depth_mm = Column(Integer, nullable=True)
    model_license = Column(String(100), nullable=True)
    model_source = Column(String(255), nullable=True)
    model_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    model_reviewed_by = Column(String(100), nullable=True)
    model_review_note = Column(String(500), nullable=True)
    model_spec_json = Column(
        JSON, nullable=True
    )  # 3D 建模真实参数（尺寸/结构/造型/材质PBR/工艺）
    data_origin = Column(
        String(30),
        nullable=False,
        default="unknown",
        server_default="unknown",
        index=True,
    )  # unknown / merchant / demo / public_reference
    source_name = Column(String(100), nullable=True)
    source_url = Column(String(500), nullable=True)
    source_product_id = Column(String(100), nullable=True)
    source_retrieved_at = Column(DateTime(timezone=True), nullable=True)
    price_observed_at = Column(DateTime(timezone=True), nullable=True)
    price_note = Column(String(500), nullable=True)
    source_metadata = Column(JSON, nullable=True)
    verification_status = Column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    availability_status = Column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
        index=True,
    )
    region_codes = Column(JSON, nullable=False, default=list)
    stock_quantity = Column(Integer, nullable=True)
    lead_time_days_min = Column(Integer, nullable=True)
    lead_time_days_max = Column(Integer, nullable=True)
    price_valid_from = Column(DateTime(timezone=True), nullable=True, index=True)
    price_valid_to = Column(DateTime(timezone=True), nullable=True, index=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(String(100), nullable=True)
    data_version = Column(
        String(100), nullable=False, default="draft-v1", server_default="draft-v1"
    )
    record_version = Column(Integer, nullable=False, default=1, server_default="1")
    alternative_skus = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    assets = relationship(
        "ProductAsset",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductAsset.id",
    )
    audit_events = relationship(
        "ProductAuditEvent",
        back_populates="product",
        order_by="ProductAuditEvent.id",
    )


class ProductAuditEvent(Base):
    """商品商业事实与审核决定的追加式审计事件。"""

    __tablename__ = "product_audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('commercial_created', 'commercial_patch', "
            "'commercial_deactivate', 'commercial_excel_created', "
            "'commercial_excel_updated', 'commercial_review_approve', "
            "'commercial_review_reject')",
            name="ck_product_audit_event_type",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('approve', 'reject')",
            name="ck_product_audit_decision",
        ),
        CheckConstraint(
            "resulting_status IN ('draft', 'verified', 'rejected', 'expired')",
            name="ck_product_audit_resulting_status",
        ),
        CheckConstraint(
            "resulting_record_version >= 1",
            name="ck_product_audit_record_version",
        ),
        CheckConstraint(
            "(idempotency_key IS NULL AND payload_hash IS NULL) OR "
            "(idempotency_key IS NOT NULL AND payload_hash IS NOT NULL)",
            name="ck_product_audit_idempotency_pair",
        ),
        UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_product_audit_product_idempotency",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(40), nullable=False, index=True)
    actor = Column(String(100), nullable=False, index=True)
    request_id = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=True)
    payload_hash = Column(String(64), nullable=True)
    changed_fields = Column(JSON, nullable=False, default=list)
    changes = Column(JSON, nullable=False, default=dict)
    decision = Column(String(20), nullable=True, index=True)
    resulting_status = Column(String(20), nullable=False, index=True)
    resulting_record_version = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    product = relationship("Product", back_populates="audit_events")


class ProductAsset(Base):
    """商品图片、CAD、GLB 与材质资产的来源和审核事实。"""

    __tablename__ = "product_assets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('image', 'cad', 'glb', 'material')",
            name="ck_product_assets_kind",
        ),
        CheckConstraint(
            "review_status IN ('pending_review', 'approved', 'rejected', 'superseded')",
            name="ck_product_assets_review_status",
        ),
        UniqueConstraint(
            "product_id",
            "kind",
            "url",
            name="uq_product_assets_product_kind_url",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(20), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    source = Column(String(500), nullable=True)
    authorization = Column(String(500), nullable=True)
    review_status = Column(
        String(20),
        nullable=False,
        default="pending_review",
        server_default="pending_review",
        index=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(100), nullable=True)
    review_note = Column(String(500), nullable=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="assets")


class CustomQuoteRule(Base):
    """定制类项目报价规则（衣柜 / 橱柜 / 背景墙等，按面积或延米计价）。"""

    __tablename__ = "custom_quote_rules"
    __table_args__ = (
        CheckConstraint("waste_rate_bps >= 0 AND waste_rate_bps <= 10000"),
        CheckConstraint("minimum_quantity >= 0"),
        CheckConstraint("installation_fee >= 0"),
        CheckConstraint("shipping_fee >= 0"),
        CheckConstraint("tax_rate_bps >= 0 AND tax_rate_bps <= 10000"),
        CheckConstraint("record_version >= 1"),
    )
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(
        String(100), nullable=False, index=True
    )  # 定制衣柜 / 橱柜地柜 ...
    category = Column(String(50), index=True)  # 柜类定制 / 厨房定制 / 背景墙 / 其他
    pricing_unit = Column(String(20), nullable=False)  # ㎡ / 延米 / 项
    material_grade = Column(String(50), nullable=True)  # 颗粒板 / 多层实木 / 实木 ...
    unit_price = Column(Integer, nullable=False)  # 单价（元/计价单位）
    region_codes = Column(JSON, nullable=False, default=list)
    waste_rate_bps = Column(Integer, nullable=False, default=0, server_default="0")
    minimum_quantity = Column(Float, nullable=False, default=0, server_default="0")
    installation_fee = Column(Integer, nullable=False, default=0, server_default="0")
    shipping_fee = Column(Integer, nullable=False, default=0, server_default="0")
    tax_rate_bps = Column(Integer, nullable=False, default=0, server_default="0")
    data_version = Column(
        String(100), nullable=False, default="draft-v1", server_default="draft-v1"
    )
    record_version = Column(Integer, nullable=False, default=1, server_default="1")
    description = Column(Text, nullable=True)  # 包含内容说明
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RenderedImage(Base):
    __tablename__ = "rendered_images"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scene_version_id = Column(
        Integer,
        ForeignKey("design_scene_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    plan_id = Column(String(20), index=True)  # plan-a / plan-b / plan-c
    prompt = Column(Text)
    image_url = Column(String(255))
    mode = Column(String(20))  # controlnet / text2img
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EffectRenderJob(Base):
    """独立 Worker 消费的效果图生成任务。"""

    __tablename__ = "effect_render_jobs"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_effect_render_jobs_task_idempotency",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scene_id = Column(
        Integer,
        ForeignKey("design_scenes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    scene_version_id = Column(
        Integer,
        ForeignKey("design_scene_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    scene_version = Column(Integer, nullable=True)
    scene_snapshot_json = Column(JSON, nullable=True)
    scene_digest = Column(String(71), nullable=True)
    source_image_id = Column(
        Integer,
        ForeignKey("uploaded_images.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_image_digest = Column(String(71), nullable=True)
    prompt_snapshot = Column(Text, nullable=False)
    prompt_digest = Column(String(71), nullable=False)
    request_digest = Column(String(71), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_id = Column(String(100), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=2)
    worker_id = Column(String(100), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    execution_deadline_at = Column(DateTime(timezone=True), nullable=False, index=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True, index=True)
    rendered_image_id = Column(
        Integer,
        ForeignKey("rendered_images.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    output_url = Column(String(500), nullable=True)
    mode = Column(String(20), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    plan_version = relationship("DesignPlanVersion")
    source_image = relationship("UploadedImage")
    rendered_image = relationship("RenderedImage")


class AnonymousSession(Base):
    """无需登录的客户会话，承载上传图片、设计任务和后续方案版本。"""

    __tablename__ = "anonymous_sessions"
    id = Column(String(36), primary_key=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class AnonymousSessionImage(Base):
    """匿名会话与上传图片的所有权关系。"""

    __tablename__ = "anonymous_session_images"
    session_id = Column(
        String(36),
        ForeignKey("anonymous_sessions.id"),
        primary_key=True,
    )
    image_id = Column(
        Integer,
        ForeignKey("uploaded_images.id"),
        primary_key=True,
        unique=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AnonymousSessionTask(Base):
    """匿名会话与设计任务的所有权关系。"""

    __tablename__ = "anonymous_session_tasks"
    session_id = Column(
        String(36),
        ForeignKey("anonymous_sessions.id"),
        primary_key=True,
    )
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id"),
        primary_key=True,
        unique=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DemoAgentInvocation(Base):
    """公开 Demo 模型调用的幂等、无原始指令成本账本。"""

    __tablename__ = "demo_agent_invocations"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "operation_key",
            name="uq_demo_agent_invocations_session_operation",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        String(36),
        ForeignKey("anonymous_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_key = Column(String(71), nullable=False)
    request_digest = Column(String(71), nullable=False)
    status = Column(String(20), nullable=False, default="running", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    billing_status = Column(String(20), nullable=False, default="not_billable")
    cost_cny = Column(Float, nullable=True)
    usage_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)
    error_code = Column(String(50), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class DesignRevision(Base):
    """一次完整方案生成的不可变版本。"""

    __tablename__ = "design_revisions"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "version",
            name="uq_design_revisions_task_version",
        ),
        UniqueConstraint(
            "task_id",
            "client_mutation_id",
            name="uq_design_revisions_task_client_mutation",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    requirement_snapshot = Column(JSON, nullable=False)
    image_context_snapshot = Column(JSON, nullable=True)
    workflow_trace_snapshot = Column(JSON, nullable=True)
    generator = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="completed")
    client_mutation_id = Column(String(100), nullable=True)
    mutation_digest = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plans = relationship(
        "DesignPlanVersion",
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="DesignPlanVersion.id",
    )


class DesignPlanVersion(Base):
    """某次生成中的单套方案快照。"""

    __tablename__ = "design_plan_versions"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "plan_key",
            name="uq_design_plan_versions_revision_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(
        Integer,
        ForeignKey("design_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_key = Column(String(50), nullable=False)
    plan_name = Column(String(200), nullable=False)
    style = Column(String(100), nullable=True)
    plan_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    revision = relationship("DesignRevision", back_populates="plans")
    quote_snapshot = relationship(
        "QuoteSnapshot",
        back_populates="plan_version",
        cascade="all, delete-orphan",
        uselist=False,
    )
    scene = relationship(
        "DesignScene",
        back_populates="plan_version",
        cascade="all, delete-orphan",
        uselist=False,
    )


class DesignScene(Base):
    """一套方案当前正在编辑的 3D 场景。"""

    __tablename__ = "design_scenes"

    id = Column(Integer, primary_key=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    current_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    plan_version = relationship("DesignPlanVersion", back_populates="scene")
    versions = relationship(
        "DesignSceneVersion",
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="DesignSceneVersion.version",
    )


class DesignSceneVersion(Base):
    """3D 场景的不可变历史快照。"""

    __tablename__ = "design_scene_versions"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "version",
            name="uq_design_scene_versions_scene_version",
        ),
        UniqueConstraint(
            "scene_id",
            "client_mutation_id",
            name="uq_scene_versions_scene_client_mutation",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scene_id = Column(
        Integer,
        ForeignKey("design_scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    scene_json = Column(JSON, nullable=False)
    validation_json = Column(JSON, nullable=False)
    source = Column(String(20), nullable=False, default="manual")
    client_mutation_id = Column(String(100), nullable=True)
    mutation_digest = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scene = relationship("DesignScene", back_populates="versions")


class LayoutRun(Base):
    """一次确定性布局生成的元数据：输入摘要 + 评分 + 问题分布。

    用于量化布局引擎质量、对比模型/规则改动前后的通过率，
    并配合用户的场景修改行为反推失败类型（M3 评测体系）。
    """

    __tablename__ = "layout_runs"

    id = Column(Integer, primary_key=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_version_id = Column(
        Integer,
        ForeignKey("design_scene_versions.id", ondelete="CASCADE"),
        nullable=True,
    )
    room_name = Column(String(50), nullable=True)
    room_width_m = Column(Float, nullable=True)
    room_depth_m = Column(Float, nullable=True)
    furniture_count = Column(Integer, nullable=False, default=0)
    candidate_count = Column(Integer, nullable=False, default=0)
    best_score = Column(Integer, nullable=False, default=0)
    best_valid = Column(Boolean, nullable=False, default=False)
    issue_codes = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    source = Column(String(30), nullable=False, default="auto_layout")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BlenderRenderJob(Base):
    """独立 Worker 消费的不可变场景渲染作业。"""

    __tablename__ = "blender_render_jobs"
    __table_args__ = (
        UniqueConstraint(
            "scene_version_id",
            "profile",
            name="uq_blender_render_jobs_version_profile",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)
    scene_id = Column(
        Integer,
        ForeignKey("design_scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_version_id = Column(
        Integer,
        ForeignKey("design_scene_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_version = Column(Integer, nullable=False)
    profile = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=2, server_default="2")
    worker_id = Column(String(100), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    execution_deadline_at = Column(DateTime(timezone=True), nullable=False, index=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True, index=True)
    output_url = Column(String(500), nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class QuoteSnapshot(Base):
    """与单套方案绑定的确定性报价快照。"""

    __tablename__ = "quote_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    currency = Column(String(10), nullable=False, default="CNY")
    furniture_total = Column(Integer, nullable=False, default=0)
    custom_total = Column(Integer, nullable=False, default=0)
    grand_total = Column(Integer, nullable=False, default=0)
    quote_json = Column(JSON, nullable=False)
    catalog_version = Column(
        String(100), nullable=False, default="legacy", server_default="legacy"
    )
    price_version = Column(
        String(100), nullable=False, default="legacy", server_default="legacy"
    )
    rule_version = Column(
        String(100), nullable=False, default="legacy", server_default="legacy"
    )
    sku_versions_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan_version = relationship(
        "DesignPlanVersion",
        back_populates="quote_snapshot",
    )


class PlanShare(Base):
    """绑定不可变方案版本的公开分享快照；不持久化原始 token。"""

    __tablename__ = "plan_shares"

    id = Column(Integer, primary_key=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_digest = Column(String(64), nullable=False, unique=True, index=True)
    snapshot_json = Column(JSON, nullable=False)
    snapshot_digest = Column(String(71), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan_version = relationship("DesignPlanVersion")


class GenerationRun(Base):
    """一次可恢复、可查询的后台方案生成任务。"""

    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt",
            name="uq_generation_runs_task_attempt",
        ),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_generation_runs_task_idempotency",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id"),
        nullable=False,
        index=True,
    )
    attempt = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    current_node = Column(String(50), nullable=True)
    generator = Column(String(20), nullable=True)
    error_message = Column(Text, nullable=True)
    # ---- 生成元数据（M3：换模型/改 Prompt 后量化质量与成本） ----
    model = Column(String(100), nullable=True)
    prompt_snapshot = Column(Text, nullable=True)  # 静态 Prompt/Schema/工具契约
    prompt_digest = Column(String(71), nullable=True)
    rules_digest = Column(String(71), nullable=True)
    data_digest = Column(String(71), nullable=True)
    input_snapshot = Column(JSON, nullable=True)  # 本次模型调用的完整动态输入
    input_digest = Column(String(71), nullable=True)
    provenance_schema_version = Column(Integer, nullable=True)
    output_snapshot = Column(
        JSON, nullable=True
    )  # 方案摘要（名称/风格/预算/评分/家具数）
    usage_json = Column(JSON, nullable=True)  # token 用量（prompt/completion/total）
    cost_cny = Column(Float, nullable=True)  # 估算成本（配置单价后才有值）
    cost_reserved_cny = Column(Float, nullable=False, default=0.0, server_default="0")
    cost_limit_cny = Column(Float, nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    worker_id = Column(String(100), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    execution_deadline_at = Column(DateTime(timezone=True), nullable=True, index=True)
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True, index=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(100), nullable=True)
    request_digest = Column(String(71), nullable=True)
    result_revision_id = Column(
        Integer,
        ForeignKey("design_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
        index=True,
    )
    output_digest = Column(String(71), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    events = relationship(
        "GenerationRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="GenerationRunEvent.id",
    )
    result_revision = relationship("DesignRevision")
    scene_evidence = relationship(
        "GenerationRunSceneEvidence",
        back_populates="generation_run",
        cascade="all, delete-orphan",
        order_by="GenerationRunSceneEvidence.plan_version_id",
    )


class GenerationRunSceneEvidence(Base):
    """生成运行逐方案冻结的 3D 场景版本引用与内容摘要。"""

    __tablename__ = "generation_run_scene_evidence"
    __table_args__ = (
        UniqueConstraint(
            "generation_run_id",
            "plan_version_id",
            name="uq_generation_run_scene_plan",
        ),
        UniqueConstraint(
            "generation_run_id",
            "scene_id",
            name="uq_generation_run_scene",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    generation_run_id = Column(
        Integer,
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scene_id = Column(
        Integer,
        ForeignKey("design_scenes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scene_version_id = Column(
        Integer,
        ForeignKey("design_scene_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scene_version = Column(Integer, nullable=False)
    scene_digest = Column(String(71), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    generation_run = relationship(
        "GenerationRun",
        back_populates="scene_evidence",
    )


class EvaluationRunBinding(Base):
    """评测案例与正式生成运行的不可变输入绑定。"""

    __tablename__ = "evaluation_run_bindings"

    id = Column(Integer, primary_key=True, index=True)
    generation_run_id = Column(
        Integer,
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    task_id = Column(
        Integer,
        ForeignKey("design_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_fingerprint = Column(String(71), nullable=False, index=True)
    asset_digest = Column(String(71), nullable=False)
    task_input_digest = Column(String(71), nullable=False)
    dataset_split = Column(String(20), nullable=True)
    model = Column(String(100), nullable=True)
    prompt_digest = Column(String(71), nullable=True)
    rules_digest = Column(String(71), nullable=True)
    data_digest = Column(String(71), nullable=True)
    input_digest = Column(String(71), nullable=True)
    provenance_schema_version = Column(Integer, nullable=True)
    requirement_parse_result_id = Column(
        Integer,
        ForeignKey("requirement_parse_results.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    uploaded_image_id = Column(
        Integer,
        ForeignKey("uploaded_images.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prediction_snapshot_json = Column(JSON, nullable=True)
    prediction_digest = Column(String(71), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GenerationRunEvent(Base):
    """后台生成任务的单个 LangGraph 节点事件。"""

    __tablename__ = "generation_run_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    progress = Column(Integer, nullable=False)
    source = Column(String(30), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    detail_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("GenerationRun", back_populates="events")


class ModelProviderCircuit(Base):
    """跨 Worker 共享的模型供应商熔断状态。"""

    __tablename__ = "model_provider_circuits"

    provider_key = Column(String(100), primary_key=True)
    state = Column(String(20), nullable=False, default="closed", index=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    cooldown_until = Column(DateTime(timezone=True), nullable=True, index=True)
    probe_token = Column(String(36), nullable=True, unique=True)
    probe_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_failure_code = Column(String(50), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkerHeartbeat(Base):
    """跨进程 Worker 存活状态；任务租约心跳不能替代空闲进程心跳。"""

    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        UniqueConstraint(
            "worker_type",
            "worker_id",
            name="uq_worker_heartbeats_type_identity",
        ),
    )

    id = Column(Integer, primary_key=True)
    worker_type = Column(String(30), nullable=False, index=True)
    worker_id = Column(String(200), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    heartbeat_at = Column(DateTime(timezone=True), nullable=False, index=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True, index=True)


class SmsCode(Base):
    """手机号验证码。Mock 阶段使用固定 code，生产切换到真实短信服务商。"""

    __tablename__ = "sms_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    code = Column(String(10), nullable=False)
    purpose = Column(String(20), nullable=False, default="login")  # login / register
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    """订单意向：普通用户发布，厂家在订单池接单并报价。"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(40), unique=True, index=True, nullable=False)
    customer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # plan：基于已生成方案发布；requirement：纯需求意向
    source_type = Column(String(20), nullable=False, default="requirement")
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True, index=True)
    plan_version_id = Column(
        Integer,
        ForeignKey("design_plan_versions.id"),
        nullable=True,
    )
    title = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    budget_min = Column(Integer, nullable=True)
    budget_max = Column(Integer, nullable=True)
    # open / quoted / assigned / closed / cancelled
    status = Column(String(20), nullable=False, default="open", index=True)
    assigned_factory_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_quote_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OrderQuote(Base):
    """厂家对某订单的一次报价。"""

    __tablename__ = "order_quotes"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    factory_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    total_price = Column(Integer, nullable=False)
    price_min = Column(Integer, nullable=True)
    price_max = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    # pending / accepted / rejected
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
