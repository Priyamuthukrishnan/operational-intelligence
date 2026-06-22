"""
backend/core/config.py
Pydantic Settings configurations. Loads and validates environment variables from .env file.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application-wide configuration loaded from environment variables."""

    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "Operational Intelligence"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://localhost:5432/operational_intelligence"

    # ── API ──────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ── AI Services ──────────────────────────────────────────────────────
    MISTRAL_API_KEY: Optional[str] = None
    LLM_MODEL: str = "mistral-small-latest"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()