"""
backend/api/v1/endpoints/clustering.py
REST API endpoints for customer groupings, issue clusters, and repeat issue detections.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.core.logging import setup_logger
from backend.schemas.clustering import CustomerClusteringResponse
from backend.services.customer_clustering_service import CustomerClusteringService

logger = setup_logger(__name__)

router = APIRouter()


@router.get(
    "/customer/{customer_id}",
    response_model=CustomerClusteringResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve customer clustering and similarity analysis",
    description=(
        "Returns clustering analysis for a specific customer including "
        "interaction count, enrichment feature state, repeat-pattern "
        "metadata, and dynamically computed pending dependency information. "
        "When Qdrant vectors are available, performs nearest-neighbour "
        "similarity search and returns similarity groups with scores. "
        "Similarity results are returned even when clustering_ready is "
        "false (i.e. other enrichment dependencies are still pending). "
        "Phase 2 additions: customer-level cluster summary with repeat "
        "metrics, deduplicated issue clusters via semantic similarity, "
        "and time-based clusters at daily, weekly, and monthly granularity. "
        "Any generated issue clusters of size > 1 are persisted to the "
        "PostgreSQL database and associated interactions are mapped. "
        "Includes repeat-issue clusters (parent/subticket) grouped "
        "chronologically by semantic similarity."
    ),
)
def get_customer_clustering(
    customer_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> CustomerClusteringResponse:
    """Assess clustering readiness for a customer.

    The endpoint validates the UUID path parameter, delegates processing
    to :class:`CustomerClusteringService`, and returns a dynamically
    generated readiness report.

    Args:
        customer_id: UUID of the customer (validated by FastAPI/Pydantic).
        db: Database session injected via dependency.

    Raises:
        404: No interaction records found for the given customer.
        500: Unexpected internal error.
    """
    try:
        service = CustomerClusteringService(db)
        interactions = service.get_customer_interactions(customer_id)

        if not interactions:
            logger.warning(
                "No interactions found for customer_id=%s",
                customer_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No interactions found for customer {customer_id}",
            )

        return service.group_customer_issues(customer_id)

    except HTTPException:
        # Let explicit HTTP exceptions propagate untouched.
        raise

    except Exception as exc:
        logger.exception(
            "Unhandled error in get_customer_clustering endpoint "
            "for customer_id=%s",
            customer_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc
