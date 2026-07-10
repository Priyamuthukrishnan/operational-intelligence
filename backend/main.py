"""
main.py
FastAPI application main entrypoint. Handles server startup, lifecycle events,
middleware configurations, and routing integrations.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.api import api_router
from core.config import get_settings
from core.logging import setup_logger

logger = setup_logger(__name__)
settings = get_settings()


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    logger.info(
        "Starting %s v%s", settings.APP_NAME, settings.APP_VERSION
    )
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


# ── Application factory ─────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Operational Intelligence platform — analytics and enrichment layer",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ── Health check ──────────────────────────────────────────────────────────

@app.get("/", tags=["root"])
def root() -> dict[str, str]:
    """Root endpoint for basic API health and discovery."""
    return {"message": "Operational Intelligence API"}

@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Liveness probe for orchestrators and load balancers."""
    return {"status": "healthy"}
