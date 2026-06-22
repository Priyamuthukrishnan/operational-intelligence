"""
backend/api/v1/api.py
API Version 1 Router. Includes and aggregates routers from endpoint modules.
"""

from fastapi import APIRouter

from backend.api.v1.endpoints import events

api_router = APIRouter()

# ── Event Capture ────────────────────────────────────────────────────────
api_router.include_router(
    events.router,
    prefix="/events",
    tags=["events"],
)
