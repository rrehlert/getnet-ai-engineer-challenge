import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Runtime configuration, read from env vars and `.env` (see spec: Configuration)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "openai:openai/gpt-6-luna"
    openai_api_key: str | None = None
    openai_base_url: str = "https://openrouter.ai/api/v1"
    tavily_api_key: str = ""
    # Off by default so tests never call a judge; compose turns it on.
    judge_enabled: bool = False
    # Pick a model from a different family than `llm_model` so the Judge doesn't grade its own writing.
    judge_model: str = "openai:anthropic/claude-haiku-5.5"
    relevance_threshold: float = 0.5
    port: int = 8000
    # Persistent Chroma index (gitignored; built at startup, not baked into the image).
    chroma_dir: str = "chroma"


def warn_if_judge_not_independent(settings: Settings) -> None:
    """Log a warning when the Judge would rate replies from the very model that wrote them."""
    if settings.judge_model == settings.llm_model:
        log.warning(
            "JUDGE_MODEL equals LLM_MODEL (%s): Judges will rate replies written by the same model",
            settings.llm_model,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
