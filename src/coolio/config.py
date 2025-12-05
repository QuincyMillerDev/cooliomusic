"""Configuration settings for Coolio."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ElevenLabs
    elevenlabs_api_key: str = Field(..., alias="ELEVENLABS_API_KEY")

    # Stability AI (Stable Audio)
    stability_api_key: str = Field(..., alias="STABILITY_API_KEY")
    stable_audio_model: str = Field(
        default="stable-audio-2.5",
        alias="STABLE_AUDIO_MODEL",
    )

    # OpenRouter (OpenAI-compatible API for multi-model support)
    openrouter_api_key: str = Field(..., alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="anthropic/claude-opus-4.5",
        alias="OPENROUTER_MODEL",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )

    # Cloudflare R2 Storage
    r2_access_key_id: str = Field(..., alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field(..., alias="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str = Field(default="cooliomusicstorage", alias="R2_BUCKET_NAME")
    r2_endpoint_url: str = Field(
        default="https://ccbe407ceb8cc78fc1ec28cbb02894b0.r2.cloudflarestorage.com",
        alias="R2_ENDPOINT_URL",
    )

    # Output settings
    output_dir: Path = Field(default=Path("output/audio"))

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Get settings instance (lazy-loaded, cached)."""
    return Settings()  # type: ignore[call-arg]

