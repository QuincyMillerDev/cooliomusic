"""Configuration settings for Coolio."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ElevenLabs
    elevenlabs_api_key: str = Field(..., alias="ELEVENLABS_API_KEY")

    # OpenRouter (OpenAI-compatible API for multi-model support)
    openrouter_api_key: str = Field(..., alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-4.5",
        alias="OPENROUTER_MODEL",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )

    # Output settings
    output_dir: Path = Field(default=Path("output/audio"))

    # Generation defaults
    default_track_count: int = Field(default=5)
    default_track_duration_ms: int = Field(default=180000)  # 3 minutes
    max_track_duration_ms: int = Field(default=300000)  # 5 minutes (ElevenLabs limit)
    min_track_duration_ms: int = Field(default=10000)  # 10 seconds (ElevenLabs limit)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Get settings instance (lazy-loaded, cached)."""
    return Settings()  # type: ignore[call-arg]

