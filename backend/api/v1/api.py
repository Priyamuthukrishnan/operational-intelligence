"""
backend/api/v1/api.py
API Version 1 Router. Includes and aggregates routers from endpoint modules.
"""

from fastapi import APIRouter

from backend.api.v1.endpoints import clustering, events, intelligence, dashboard

api_router = APIRouter()

# ── Event Capture ────────────────────────────────────────────────────────
api_router.include_router(
    events.router,
    prefix="/events",
    tags=["events"],
)

# ── Customer Clustering ──────────────────────────────────────────────────
api_router.include_router(
    clustering.router,
    prefix="/clustering",
    tags=["clustering"],
)

# ── Dashboards ───────────────────────────────────────────────────────────
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["dashboard"],
)

