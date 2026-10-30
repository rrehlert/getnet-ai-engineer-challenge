from app.llm import make_chat_model
from app.settings import Settings


def test_default_model_points_at_openrouter_with_timeout_and_retries():
    settings = Settings(_env_file=None, openai_api_key="sk-test")

    model = make_chat_model(settings)

    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "openai/gpt-6-luna"
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    assert model.request_timeout == 30
    assert model.max_retries == 2


def test_model_name_override_is_used_for_judges():
    settings = Settings(_env_file=None, openai_api_key="sk-test")

    model = make_chat_model(settings, "openai:openai/judge-x")

    assert model.model_name == "openai/judge-x"
