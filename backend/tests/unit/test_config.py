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
