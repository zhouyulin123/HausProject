import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_model_configuration_uses_provider_neutral_environment_names(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "llm-secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "provider/chat-model")
    monkeypatch.setenv("VL_API_KEY", "vl-secret")
    monkeypatch.setenv("VL_BASE_URL", "https://vl.example.com/v1")
    monkeypatch.setenv("VL_MODEL", "provider/vision-model")
    monkeypatch.setenv("VL_REASONING_MODEL", "provider/vision-reasoning-model")

    config = Settings(_env_file=None)

    assert config.llm_api_key == "llm-secret"
    assert config.llm_base_url == "https://llm.example.com/v1"
    assert config.llm_model == "provider/chat-model"
    assert config.vl_api_key == "vl-secret"
    assert config.vl_base_url == "https://vl.example.com/v1"
    assert config.vl_model == "provider/vision-model"
    assert config.vl_reasoning_model == "provider/vision-reasoning-model"


def test_model_configuration_accepts_legacy_environment_names(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-llm-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://legacy-llm.example.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "legacy/chat-model")
    monkeypatch.setenv("VL_API_KEY_BASE_URL", "https://legacy-vl.example.com/v1")
    monkeypatch.setenv("VL_MODEL1", "legacy/vision-model")
    monkeypatch.setenv("VL_MODEL2", "legacy/vision-reasoning-model")

    config = Settings(_env_file=None)

    assert config.llm_api_key == "legacy-llm-secret"
    assert config.llm_base_url == "https://legacy-llm.example.com/v1"
    assert config.llm_model == "legacy/chat-model"
    assert config.vl_base_url == "https://legacy-vl.example.com/v1"
    assert config.vl_model == "legacy/vision-model"
    assert config.vl_reasoning_model == "legacy/vision-reasoning-model"


def test_debug_is_disabled_by_default():
    config = Settings(_env_file=None)

    assert config.app_debug is False


def test_generation_worker_heartbeat_must_be_shorter_than_lease():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            generation_worker_heartbeat_seconds=60,
            generation_worker_lease_seconds=60,
        )


def test_generation_worker_execution_timeout_must_be_positive_and_bounded():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            generation_worker_execution_timeout_seconds=0,
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            generation_worker_execution_timeout_seconds=7201,
        )


@pytest.mark.parametrize(
    ("database_url", "jwt_secret_key"),
    [
        (
            "mysql+pymysql://root:123456@127.0.0.1:3306/houseproject_db",
            "a-production-secret-that-is-long-enough",
        ),
        (
            "mysql+pymysql://app:strong-password@db:3306/houseproject_db",
            "dev-secret-change-me-in-production",
        ),
    ],
)
def test_production_rejects_unsafe_database_or_jwt_defaults(
    database_url,
    jwt_secret_key,
):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            app_debug=False,
            database_url=database_url,
            jwt_secret_key=jwt_secret_key,
            cors_origins="https://app.example.com",
        )


def test_production_accepts_explicit_safe_configuration():
    config = Settings(
        _env_file=None,
        app_env="production",
        app_debug=False,
        database_url=(
            "mysql+pymysql://haus_app:a-strong-database-password@db:3306/houseproject_db"
        ),
        jwt_secret_key="a-production-jwt-secret-with-at-least-32-characters",
        cors_origins="https://app.example.com",
    )

    assert config.app_env == "production"
    assert config.cors_origin_list == ["https://app.example.com"]


def test_production_rejects_inline_generation_fallback():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            app_debug=False,
            database_url=(
                "mysql+pymysql://haus_app:a-strong-database-password@db:3306/houseproject_db"
            ),
            jwt_secret_key="a-production-jwt-secret-with-at-least-32-characters",
            cors_origins="https://app.example.com",
            generation_inline_fallback=True,
        )
