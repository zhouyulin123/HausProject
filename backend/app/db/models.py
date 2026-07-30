from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    openid = Column(String(100), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    nickname = Column(String(50), nullable=True)
    avatar = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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


class UploadedImage(Base):
    __tablename__ = "uploaded_images"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True)
    image_type = Column(String(50), default="room_photo")  # room_photo / floor_plan / reference_image
    file_url = Column(String(255))
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    analysis_json = Column(JSON, nullable=True)  # AI 空间识别结果
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RequirementParseResult(Base):
    __tablename__ = "requirement_parse_results"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), index=True)
    raw_input = Column(Text)
    parsed_json = Column(JSON)
    missing_fields = Column(JSON, nullable=True)
    follow_up_questions = Column(JSON, nullable=True)
    parser = Column(String(20), default="rule")  # llm / rule
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
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True, index=True)
    role = Column(String(10))  # user / ai
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CustomQuoteRule(Base):
    """定制类项目报价规则（衣柜 / 橱柜 / 背景墙等，按面积或延米计价）。"""

    __tablename__ = "custom_quote_rules"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String(100), nullable=False, index=True)  # 定制衣柜 / 橱柜地柜 ...
    category = Column(String(50), index=True)  # 柜类定制 / 厨房定制 / 背景墙 / 其他
    pricing_unit = Column(String(20), nullable=False)  # ㎡ / 延米 / 项
    material_grade = Column(String(50), nullable=True)  # 颗粒板 / 多层实木 / 实木 ...
    unit_price = Column(Integer, nullable=False)  # 单价（元/计价单位）
    description = Column(Text, nullable=True)  # 包含内容说明
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RenderedImage(Base):
    __tablename__ = "rendered_images"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("design_tasks.id"), nullable=True, index=True)
    plan_id = Column(String(20), index=True)  # plan-a / plan-b / plan-c
    prompt = Column(Text)
    image_url = Column(String(255))
    mode = Column(String(20))  # controlnet / text2img
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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


class DesignRevision(Base):
    """一次完整方案生成的不可变版本。"""

    __tablename__ = "design_revisions"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "version",
            name="uq_design_revisions_task_version",
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan_version = relationship(
        "DesignPlanVersion",
        back_populates="quote_snapshot",
    )


class GenerationRun(Base):
    """一次可恢复、可查询的后台方案生成任务。"""

    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt",
            name="uq_generation_runs_task_attempt",
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    events = relationship(
        "GenerationRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="GenerationRunEvent.id",
    )


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
