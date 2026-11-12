import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

# How the request line logs the Message: `none` (length only), `redacted`, or `full` (raw, still capped).
MessageMode = Literal["none", "redacted", "full"]


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
    # All persistent state (gitignored): the Corpus index (`chroma/`, built at startup, not baked
    # into the image) and the Conversations database (`conversations.db`). One volume in compose.
    state_dir: str = "state"
    # HMAC key for `user_ref` in logs; empty means a random key per process (refs don't match across restarts).
    log_hash_key: str = ""
    log_messages: MessageMode = "redacted"
    # HS256 key for login tokens; empty means a random secret per process (tokens die on restart).
    jwt_secret: str = ""
    # Enables `POST /dev/login` ("log in as" any user id). Off by default; compose turns it on.
    demo_login: bool = False

    @property
    def chroma_dir(self) -> Path:
        return Path(self.state_dir) / "chroma"

    @property
    def database_path(self) -> Path:
        return Path(self.state_dir) / "conversations.db"


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
