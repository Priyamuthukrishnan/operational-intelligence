"""Event-driven worker for computing and persisting risk scores."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.core.logging import setup_logger
from backend.db.session import SessionLocal
from backend.intelligence.risk_scorer import compute
from backend.repositories.interaction_repository import InteractionRepository

logger = setup_logger(__name__)


def process_ticket_risk(
    ticket_id: uuid.UUID | str,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """Compute and persist risk for one ticket snapshot history."""
    ticket_uuid = uuid.UUID(str(ticket_id))
    owns_session = db is None
    session = db or SessionLocal()
    repository = InteractionRepository(session)

    try:
        history = repository.get_ticket_history(ticket_uuid)
        if not history:
            logger.warning("No history found for ticket_id=%s", ticket_uuid)
            return None

        result = compute(history)
        latest = history[-1]

        repository.update_risk_fields(
            latest.id,
            {
                "escalation_risk_score": result["escalation_risk_score"],
                "escalation_risk_band": result["escalation_risk_band"],
                "confidence_decay_score": result["confidence_decay_score"],
                "momentum_score": result["momentum_score"],
                "risk_multiplier": result["risk_multiplier"],
                "risk_reason": result["risk_reason"],
                "risk_processed": True,
            },
        )
        session.commit()

        logger.info(
            "Risk computed for ticket_id=%s raw_score=%s signal_scores=%s multiplier=%s final_score=%s risk_band=%s",
            ticket_uuid,
            result["raw_score"],
            result["signal_scores"],
            result["risk_multiplier"],
            result["final_score"],
            result["escalation_risk_band"],
        )
        return result

    except Exception:
        session.rollback()
        logger.exception("Failed to process risk for ticket_id=%s", ticket_uuid)
        raise

    finally:
        if owns_session:
            session.close()
