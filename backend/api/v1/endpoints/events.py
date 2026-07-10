"""
api/v1/endpoints/events.py
REST API endpoint definitions for receiving and processing interaction events.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

# pyrefly: ignore [missing-import]
from api.deps import get_db
from core.logging import setup_logger
from schemas.event import EventCaptureRequest, EventCaptureResponse
from services.event_processor import EventProcessor

logger = setup_logger(__name__)

router = APIRouter()


@router.post(
    "/capture",
    response_model=EventCaptureResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Capture an interaction event",
    description=(
        "Receives a ticket interaction event from the Service Intelligence "
        "layer and persists it in the Operational Intelligence analytics "
        "database for downstream processing."
    ),
)
def capture_event(
    payload: EventCaptureRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> EventCaptureResponse:
    """Ingest a single interaction event and trigger enrichment in the background.

    The endpoint validates the request body via Pydantic, delegates
    processing to :class:`EventProcessor`, and returns the generated
    ``operational_analysis_id``.

    Raises:
        422: Pydantic validation failure (automatic).
        500: Unexpected internal error.
    """
    try:
        processor = EventProcessor(db)
        return processor.capture_event(payload, background_tasks=background_tasks)


    except HTTPException:
        # Let explicit HTTP exceptions propagate untouched.
        raise

    except Exception as exc:
        logger.exception("Unhandled error in capture_event endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        ) from exc
