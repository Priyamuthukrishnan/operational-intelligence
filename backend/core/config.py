"""
core/config.py
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
    DATABASE_URL: str = "postgresql://neondb_owner:npg_1WPURqxkdfr8@ep-still-flower-aop7bzg5-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

    # ── API ──────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ── AI Services ──────────────────────────────────────────────────────
    MISTRAL_API_KEY: Optional[str] = None
    LLM_MODEL: str = "mistral-small-latest"

    # ── Qdrant Vector Store ──────────────────────────────────────────────
    QDRANT_URL: Optional[str] = None
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_NAME: Optional[str] = None  # Must come from .env

    # ── External Embedding Service ───────────────────────────────────────
    EMBEDDING_SERVICE_URL: Optional[str] = "http://127.0.0.1:8001"

    # ── Clustering ───────────────────────────────────────────────────────
    SIMILARITY_THRESHOLD: float = 0.75
    SIMILARITY_SEARCH_LIMIT: int = 20
    TIME_CLUSTER_MIN_INTERACTIONS: int = 1

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