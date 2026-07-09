"""
backend/api/v1/endpoints/dashboard.py
REST API endpoints for executive summary metrics and operational dashboards data.
"""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.core.logging import setup_logger
from backend.services.dashboard_service import DashboardService
from backend.services.aggregation_service import AggregationService
from backend.schemas.dashboard import (
    OperationalDashboardResponse,
    ExecutiveDashboardResponse,
    CustomerDashboardResponse,
)

logger = setup_logger(__name__)

router = APIRouter()


@router.get(
    "/operational",
    response_model=OperationalDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve operational dashboard metrics",
    description="Returns aggregated metrics for support teams, including open escalations, top issue categories, and resolution statistics.",
)
def get_operational_dashboard(
    db: Session = Depends(get_db),
) -> OperationalDashboardResponse:
    """Fetch aggregated operational dashboard indicators."""
    try:
        service = DashboardService(db)
        return service.get_operational_dashboard()
    except Exception as exc:
        logger.exception("Error fetching operational dashboard metrics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc


@router.get(
    "/executive",
    response_model=ExecutiveDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve executive dashboard summary",
    description="Returns high-level summary metrics for the C-suite, including overall customer health indices, risk profiles, and weekly rolling trends.",
)
def get_executive_dashboard(
    db: Session = Depends(get_db),
) -> ExecutiveDashboardResponse:
    """Fetch executive level overview metrics."""
    try:
        service = DashboardService(db)
        return service.get_executive_dashboard()
    except Exception as exc:
        logger.exception("Error fetching executive dashboard metrics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc


@router.get(
    "/customer/{customer_id}",
    response_model=CustomerDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve customer health profile and interaction history",
    description="Returns the comprehensive health evaluation and full historical interaction list for a specific customer.",
)
def get_customer_dashboard(
    customer_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> CustomerDashboardResponse:
    """Fetch a customer profile dashboard."""
    try:
        service = DashboardService(db)
        return service.get_customer_dashboard(customer_id)
    except Exception as exc:
        logger.exception("Error fetching customer dashboard for customer_id=%s", customer_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc


@router.post(
    "/refresh-trends",
    status_code=status.HTTP_200_OK,
    summary="Trigger historical trend rollups calculation",
    description="Aggregates and recalculates daily, weekly, and monthly metric rollups across all interaction logs.",
)
def refresh_trends(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Force re-run the aggregation rollup pipeline."""
    try:
        service = AggregationService(db)
        count = service.generate_all_rollups()
        return {
            "status": "success",
            "message": f"Aggregation rollups generated successfully. Total records processed: {count}",
        }
    except Exception as exc:
        logger.exception("Error running trend rollup aggregation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc
