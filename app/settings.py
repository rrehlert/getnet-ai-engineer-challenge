from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from env vars and `.env` (see spec: Configuration)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "openai:openai/gpt-6-luna"
    openai_api_key: str | None = None
    openai_base_url: str = "https://openrouter.ai/api/v1"
    tavily_api_key: str = ""
    # Off by default so tests never call a judge; compose turns it on.
    judge_enabled: bool = False
    # Empty means "same as llm_model".
    judge_model: str = ""
    relevance_threshold: float = 0.43
    port: int = 8000

    @model_validator(mode="after")
    def _default_judge_model(self) -> "Settings":
        if not self.judge_model:
            self.judge_model = self.llm_model
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
