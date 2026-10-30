import pytest

from app.settings import Settings

ENV_VARS = [
    "LLM_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TAVILY_API_KEY",
    "JUDGE_ENABLED",
    "JUDGE_MODEL",
    "RELEVANCE_THRESHOLD",
    "PORT",
]


@pytest.fixture
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_defaults_match_spec(clean_env):
    settings = Settings(_env_file=None)

    assert settings.llm_model == "openai:openai/gpt-6-luna"
    assert settings.openai_api_key is None
    assert settings.openai_base_url == "https://openrouter.ai/api/v1"
    assert settings.tavily_api_key == ""
    assert settings.judge_enabled is False
    assert settings.judge_model == "openai:openai/gpt-6-luna"
    assert settings.relevance_threshold == 0.43
    assert settings.port == 8000


def test_judge_model_follows_llm_model_when_unset(clean_env):
    clean_env.setenv("LLM_MODEL", "anthropic:claude-x")

    assert Settings(_env_file=None).judge_model == "anthropic:claude-x"


def test_env_overrides(clean_env):
    clean_env.setenv("JUDGE_ENABLED", "true")
    clean_env.setenv("JUDGE_MODEL", "openai:judge")
    clean_env.setenv("RELEVANCE_THRESHOLD", "0.5")
    clean_env.setenv("PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.judge_enabled is True
    assert settings.judge_model == "openai:judge"
    assert settings.relevance_threshold == 0.5
    assert settings.port == 9000
