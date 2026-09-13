from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 放在项目根目录（backend 的上一级），无论从哪里启动都能找到
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    development_catalog_enabled: bool = False
    port: int = 8000
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"

    # 本地 MySQL（用户本机已部署）
    database_url: str = (
        "mysql+pymysql://root@127.0.0.1:3306/houseproject_db?charset=utf8mb4"
    )

    # 文本模型：需求解析 / 对话 / 方案生成 / Agent 规划
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"),
    )
    llm_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    llm_model: str = Field(
        default="deepseek-ai/DeepSeek-V3",
        validation_alias=AliasChoices("LLM_MODEL", "DEEPSEEK_MODEL"),
    )
    llm_provider_key: str = Field(
        default="primary-llm",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    # 可选：每百万 token 单价（元），配置后才会估算方案生成成本并写入 generation_runs
    llm_input_price_per_mtok: float | None = Field(default=None, gt=0, le=1_000_000)
    llm_output_price_per_mtok: float | None = Field(default=None, gt=0, le=1_000_000)

    # 视觉模型（SiliconFlow 上的 Qwen3-VL：户型图 / 房间照片分析）
    vl_api_key: str = ""
    vl_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        validation_alias=AliasChoices("VL_BASE_URL", "VL_API_KEY_BASE_URL"),
    )
    vl_model: str = Field(
        default="Qwen/Qwen3-VL-32B-Instruct",
        validation_alias=AliasChoices("VL_MODEL", "VL_MODEL1"),
    )
    vl_reasoning_model: str = Field(
        default="Qwen/Qwen3-VL-32B-Thinking",
        validation_alias=AliasChoices("VL_REASONING_MODEL", "VL_MODEL2"),
    )
    vl_provider_key: str = Field(
        default="primary-vl",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    vl_input_token_ceiling: int = Field(default=32768, ge=1024, le=1_000_000)
    vl_input_price_per_mtok: float | None = Field(default=None, gt=0, le=1_000_000)
    vl_output_price_per_mtok: float | None = Field(default=None, gt=0, le=1_000_000)

    # 本地效果图生成（SD1.5 + ControlNet MLSD，跑在本机 GPU）
    sd_enabled: bool = True
    sd_base_model: str = "Lykon/dreamshaper-8"
    sd_controlnet_model: str = "lllyasviel/control_v11p_sd15_mlsd"
    hf_home: str = "./hf_cache"

    # 登录与短信验证码（Mock 阶段固定验证码；生产切换到真实短信服务商）
    jwt_secret_key: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 天
    auth_cookie_name: str = "haus_session"
    sms_mock_code: str = "123456"
    sms_code_expire_seconds: int = 300  # 验证码 5 分钟有效
    sms_code_resend_seconds: int = 60  # 同手机号 60 秒内不可重发

    # 店铺信息默认值（首次启动写入 shop_settings 表；之后以数据库为准，可在 /admin 修改）
    shop_name: str = "AI 家装定制助手"
    shop_phone: str = ""
    shop_wechat: str = ""
    shop_address: str = ""
    shop_slogan: str = "让 AI 为你定制理想中的家"

    # 本地文件上传目录（backend/uploads）
    upload_dir: str = str(Path(__file__).resolve().parents[2] / "uploads")
    max_upload_image_mb: int = 10
    max_upload_model_mb: int = 25
    pdf_font_regular_path: str = ""
    pdf_font_bold_path: str = ""
    scene_agent_requests_per_minute: int = Field(default=6, ge=1, le=120)
    demo_agent_requests_per_minute: int = Field(default=6, ge=1, le=120)
    demo_agent_ip_requests_per_minute: int = Field(default=20, ge=1, le=600)
    blender_executable: str = "blender"
    blender_work_dir: str = str(
        Path(__file__).resolve().parents[2] / "worker_data" / "blender"
    )
    frontend_public_dir: str = str(
        Path(__file__).resolve().parents[3] / "frontend" / "public"
    )
    blender_render_timeout_seconds: int = Field(default=1200, ge=60, le=7200)
    blender_render_max_mb: int = Field(default=30, ge=1, le=200)
    blender_worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=60)
    blender_worker_max_attempts: int = Field(default=2, ge=1, le=5)
    blender_worker_lease_seconds: int = Field(default=180, ge=30, le=3600)
    blender_worker_heartbeat_seconds: int = Field(default=15, ge=1, le=300)
    blender_worker_execution_timeout_seconds: int = Field(default=1800, ge=60, le=14400)
    blender_worker_retry_base_seconds: int = Field(default=5, ge=1, le=600)
    blender_render_requests_per_hour: int = Field(default=10, ge=1, le=100)
    blender_allow_uploaded_models: bool = False
    generation_worker_poll_seconds: float = Field(default=1.0, ge=0.2, le=60)
    generation_worker_max_attempts: int = Field(default=3, ge=1, le=10)
    design_agent_turn_lease_seconds: int = Field(default=300, ge=30, le=3600)
    generation_worker_lease_seconds: int = Field(default=180, ge=30, le=3600)
    generation_worker_heartbeat_seconds: int = Field(default=15, ge=5, le=300)
    generation_worker_execution_timeout_seconds: int = Field(
        default=900, ge=30, le=7200
    )
    generation_task_cost_limit_cny: float = Field(default=1.0, gt=0, le=1000)
    provider_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    provider_circuit_cooldown_seconds: int = Field(default=60, ge=5, le=3600)
    provider_circuit_probe_lease_seconds: int = Field(default=30, ge=5, le=300)
    generation_worker_retry_base_seconds: int = Field(default=5, ge=1, le=600)
    generation_inline_fallback: bool = False
    effect_render_worker_poll_seconds: float = Field(default=1.0, ge=0.2, le=60)
    effect_render_worker_max_attempts: int = Field(default=2, ge=1, le=5)
    effect_render_worker_lease_seconds: int = Field(default=180, ge=30, le=3600)
    effect_render_worker_heartbeat_seconds: int = Field(default=15, ge=5, le=300)
    effect_render_worker_execution_timeout_seconds: int = Field(
        default=900, ge=30, le=7200
    )
    effect_render_worker_retry_base_seconds: int = Field(default=5, ge=1, le=600)
    worker_presence_heartbeat_seconds: int = Field(default=10, ge=1, le=300)
    worker_readiness_timeout_seconds: int = Field(default=45, ge=5, le=900)
    # 阶段 4 失败分诊报告验签；未配置时管理端同步接口关闭。
    eval_report_signing_key: str = ""
    eval_report_signing_key_id: str = Field(
        default="",
        max_length=100,
        pattern=r"^(?:[A-Za-z0-9._:-]+)?$",
    )

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.blender_worker_heartbeat_seconds >= self.blender_worker_lease_seconds:
            raise ValueError("Blender Worker 心跳间隔必须小于租约有效期")
        if (
            self.blender_worker_heartbeat_seconds
            >= self.blender_worker_execution_timeout_seconds
        ):
            raise ValueError("Blender Worker 心跳间隔必须小于执行截止时间")
        if (
            self.blender_render_timeout_seconds
            > self.blender_worker_execution_timeout_seconds
        ):
            raise ValueError("Blender 渲染超时不能超过作业执行截止时间")
        if (
            self.generation_worker_heartbeat_seconds
            >= self.generation_worker_lease_seconds
        ):
            raise ValueError("方案生成 Worker 心跳间隔必须小于租约有效期")
        if (
            self.generation_worker_heartbeat_seconds
            >= self.generation_worker_execution_timeout_seconds
        ):
            raise ValueError("方案生成 Worker 心跳间隔必须小于执行截止时间")
        if (
            self.effect_render_worker_heartbeat_seconds
            >= self.effect_render_worker_lease_seconds
        ):
            raise ValueError("效果图 Worker 心跳间隔必须小于租约有效期")
        if (
            self.effect_render_worker_heartbeat_seconds
            >= self.effect_render_worker_execution_timeout_seconds
        ):
            raise ValueError("效果图 Worker 心跳间隔必须小于执行截止时间")
        if (
            self.worker_presence_heartbeat_seconds
            >= self.worker_readiness_timeout_seconds
        ):
            raise ValueError("Worker 存活心跳间隔必须小于就绪超时时间")

        if self.development_catalog_enabled and self.app_env != "development":
            raise ValueError("DEVELOPMENT_CATALOG_ENABLED 仅允许在 development 环境启用")

        if self.app_env != "production":
            return self

        if self.app_debug:
            raise ValueError("生产环境不能启用 APP_DEBUG")

        if self.generation_inline_fallback:
            raise ValueError("生产环境不能启用 GENERATION_INLINE_FALLBACK")

        if not self.llm_api_key:
            raise ValueError("生产环境必须配置 LLM_API_KEY")
        if (
            self.llm_input_price_per_mtok is None
            or self.llm_output_price_per_mtok is None
        ):
            raise ValueError("生产环境必须配置 LLM 输入与输出 token 单价")

        if not self.vl_api_key:
            raise ValueError("生产环境必须配置 VL_API_KEY")
        if (
            self.vl_input_price_per_mtok is None
            or self.vl_output_price_per_mtok is None
        ):
            raise ValueError("生产环境必须配置 VL 输入与输出 token 单价")

        weak_jwt_values = {
            "dev-secret-change-me-in-production",
            "change_me_in_production",
        }
        if self.jwt_secret_key in weak_jwt_values or len(self.jwt_secret_key) < 32:
            raise ValueError("生产环境必须配置至少 32 位的 JWT_SECRET_KEY")

        database = urlsplit(self.database_url)
        weak_passwords = {None, "", "123456", "password", "change_me"}
        if database.username == "root" or database.password in weak_passwords:
            raise ValueError("生产环境必须使用独立数据库账号和强密码")

        if not self.cors_origin_list or any(
            "localhost" in origin or "127.0.0.1" in origin
            for origin in self.cors_origin_list
        ):
            raise ValueError("生产环境必须显式配置非本地 CORS_ORIGINS")
        return self


settings = Settings()
