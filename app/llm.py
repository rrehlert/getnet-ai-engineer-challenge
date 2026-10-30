"""Chat model factory (ADR 0001): the provider comes from `LLM_MODEL="provider:model"`."""

from collections.abc import Iterator
from typing import Literal

import httpx
import openai
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


# Provider errors (ADR 0001: any provider) -> 503. Raised only after the SDK's own
# retries are exhausted. Non-openai SDKs are recognised by status or class name.
_RETRYABLE_NAMES = ("RateLimit", "Timeout", "APIConnection", "Overloaded", "ServiceUnavailable", "InternalServerError")


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """The exception and its `__cause__` / `__context__` ancestors, each once."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _status(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_rate_limit(exc: BaseException) -> bool:
    return _status(exc) == 429 or "RateLimit" in type(exc).__name__


def _is_provider(exc: BaseException) -> bool:
    if isinstance(exc, (openai.APIError, httpx.TimeoutException, httpx.TransportError)):
        return True
    status = _status(exc)
    if status is not None and (status in (408, 429) or 500 <= status < 600):
        return True
    return any(name in type(exc).__name__ for name in _RETRYABLE_NAMES)


def is_provider_error(exc: BaseException) -> bool:
    return any(_is_provider(e) for e in _chain(exc))


def provider_error_code(exc: BaseException) -> Literal["rate_limited", "provider_unavailable"]:
    return "rate_limited" if any(_is_rate_limit(e) for e in _chain(exc)) else "provider_unavailable"
