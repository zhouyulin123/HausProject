from pathlib import Path

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

    # LLM Settings（DeepSeek：需求解析 / 对话 / 方案生成）
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 视觉模型（SiliconFlow 上的 Qwen3-VL：户型图 / 房间照片分析）
    vl_api_key: str = ""
    vl_api_key_base_url: str = "https://api.siliconflow.cn/v1"
    vl_model1: str = "Qwen/Qwen3-VL-32B-Instruct"  # 主力：图片分析、结构化输出
    vl_model2: str = "Qwen/Qwen3-VL-32B-Thinking"  # 备用：复杂户型推理

    # 本地效果图生成（SD1.5 + ControlNet MLSD，跑在本机 GPU）
    sd_enabled: bool = True
    sd_base_model: str = "Lykon/dreamshaper-8"
    sd_controlnet_model: str = "lllyasviel/control_v11p_sd15_mlsd"
    hf_home: str = "D:/hf_cache"  # 模型缓存目录（与已下载的一致）

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

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
