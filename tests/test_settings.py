import logging

import pytest

from app.settings import Settings, warn_if_judge_not_independent

ENV_VARS = [
    "LLM_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TAVILY_API_KEY",
    "JUDGE_ENABLED",
    "JUDGE_MODEL",
    "RELEVANCE_THRESHOLD",
    "PORT",
    "CHROMA_DIR",
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
    assert settings.judge_model == "openai:anthropic/claude-haiku-5.5"
    assert settings.relevance_threshold == 0.5
    assert settings.port == 8000
    assert settings.chroma_dir == "chroma"


def test_judge_model_does_not_follow_llm_model(clean_env):
    clean_env.setenv("LLM_MODEL", "anthropic:claude-x")

    assert Settings(_env_file=None).judge_model == "openai:anthropic/claude-haiku-5.5"


def test_warns_when_judge_model_equals_llm_model(clean_env, caplog):
    clean_env.setenv("LLM_MODEL", "openai:same")
    clean_env.setenv("JUDGE_MODEL", "openai:same")

    warn_if_judge_not_independent(Settings(_env_file=None))

    assert any(r.levelno == logging.WARNING and "JUDGE_MODEL" in r.getMessage() for r in caplog.records)


def test_no_warning_with_default_models(clean_env, caplog):
    warn_if_judge_not_independent(Settings(_env_file=None))

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


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
