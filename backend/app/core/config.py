from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 放在项目根目录（backend 的上一级），无论从哪里启动都能找到
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = True
    port: int = 8000

    # 本地 MySQL（用户本机已部署）
    database_url: str = (
        "mysql+pymysql://root:123456@127.0.0.1:3306/houseproject_db?charset=utf8mb4"
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
    # 可选：每百万 token 单价（元），配置后才会估算方案生成成本并写入 generation_runs
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None

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

    # 本地效果图生成（SD1.5 + ControlNet MLSD，跑在本机 GPU）
    sd_enabled: bool = True
    sd_base_model: str = "Lykon/dreamshaper-8"
    sd_controlnet_model: str = "lllyasviel/control_v11p_sd15_mlsd"
    hf_home: str = "./hf_cache"

    # 登录与短信验证码（Mock 阶段固定验证码；生产切换到真实短信服务商）
    jwt_secret_key: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 天
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
    scene_agent_requests_per_minute: int = Field(default=6, ge=1, le=120)
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
    blender_render_requests_per_hour: int = Field(default=10, ge=1, le=100)
    blender_allow_uploaded_models: bool = False

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
