"""Chat model factory (ADR 0001): the provider comes from `LLM_MODEL="provider:model"`."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.settings import Settings

TIMEOUT_S = 30
MAX_RETRIES = 2


def make_chat_model(settings: Settings, model: str | None = None) -> BaseChatModel:
    name = model or settings.llm_model
    extra = {}
    if name.startswith("openai:"):
        # OpenRouter (or any OpenAI-compatible endpoint) by default.
        extra = {"base_url": settings.openai_base_url, "api_key": settings.openai_api_key}
    return init_chat_model(name, timeout=TIMEOUT_S, max_retries=MAX_RETRIES, **extra)
