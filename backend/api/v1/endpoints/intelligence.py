"""
api/v1/endpoints/intelligence.py
REST API endpoints for querying summary, sentiment, escalation risk, root cause, and health indicators.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_db
from core.logging import setup_logger
from repositories.interaction_repository import InteractionRepository
from schemas.intelligence import TicketRiskResponse
from utils.scoring import (
    convert_sentiment_score,
    convert_escalation_risk_score,
    convert_confidence_decay_score,
)

logger = setup_logger(__name__)

router = APIRouter()


@router.get(
    "/risk/{ticket_id}",
    response_model=TicketRiskResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch stored ticket risk",
    description="Returns the latest stored escalation risk snapshot for a ticket.",
)
def get_ticket_risk(
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Return the latest stored risk snapshot for a ticket."""
    repository = InteractionRepository(db)
    analysis = repository.get_latest_analysis(ticket_id)

    if analysis is None or not analysis.risk_processed:
        logger.warning("Risk not available for ticket_id=%s", ticket_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk not available for ticket {ticket_id}",
        )

    return {
        "ticket_id": ticket_id,
        "analysis_id": analysis.id,
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": convert_sentiment_score(analysis.sentiment_score),
        "risk_score": convert_escalation_risk_score(analysis.escalation_risk_score),
        "risk_band": analysis.escalation_risk_band,
        "confidence_score": convert_confidence_decay_score(analysis.confidence_decay_score),
        "momentum_score": analysis.momentum_score,
        "risk_multiplier": analysis.risk_multiplier,
        "risk_reason": analysis.risk_reason,
        "risk_processed": analysis.risk_processed,
        "captured_at": analysis.captured_at,
    }

