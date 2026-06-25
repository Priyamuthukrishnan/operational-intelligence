"""Event-driven worker for computing and persisting risk scores."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.logging import setup_logger
from backend.db.session import SessionLocal
from backend.intelligence.risk_scorer import compute
from backend.models.operational_analysis import OperationalAnalysis
from backend.repositories.interaction_repository import InteractionRepository

logger = setup_logger(__name__)


def _fetch_ticket_signals(
    session: Session,
    ticket_id: uuid.UUID,
) -> dict[str, Any]:
    """Load supporting signals from related tables for risk scoring."""
    payload: dict[str, Any] = {
        "escalation_source": None,
        "recommendation_source": None,
        "approval_action": None,
        "ai_confidences": [],
        "ticket_status": None,
        "latest_activity_at": None,
    }

    try:
        ticket_row = session.execute(
            text(
                """
                SELECT status, updated_at
                FROM tickets
                WHERE id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if ticket_row is not None:
            payload["ticket_status"] = ticket_row["status"]
            payload["latest_activity_at"] = ticket_row["updated_at"]
    except Exception:
        logger.warning(
            "Unable to load ticket metadata for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    try:
        for row in session.execute(
            text(
                """
                SELECT source_used, confidence_score
                FROM ai_analysis
                WHERE ticket_id = :ticket_id
                ORDER BY created_at ASC NULLS LAST
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings():
            if row["source_used"] is not None:
                payload["escalation_source"] = row["source_used"]
            if row["confidence_score"] is not None:
                payload["ai_confidences"].append(float(row["confidence_score"]))
    except Exception:
        logger.warning(
            "Unable to load ai_analysis signals for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    try:
        recommendation_row = session.execute(
            text(
                """
                SELECT recommendation_source
                FROM recommendations
                WHERE ticket_id = :ticket_id
                ORDER BY created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if recommendation_row is not None:
            payload["recommendation_source"] = recommendation_row["recommendation_source"]
    except Exception:
        logger.warning(
            "Unable to load recommendation signals for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    try:
        approval_row = session.execute(
            text(
                """
                SELECT action
                FROM approval_history
                WHERE ticket_id = :ticket_id
                ORDER BY created_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if approval_row is not None:
            payload["approval_action"] = approval_row["action"]
    except Exception:
        logger.warning(
            "Unable to load approval history for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    try:
        comment_row = session.execute(
            text(
                """
                SELECT MAX(created_at) AS latest_comment_at
                FROM comments
                WHERE ticket_id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        latest_comment_at = comment_row["latest_comment_at"] if comment_row else None
        if latest_comment_at is not None:
            existing = payload["latest_activity_at"]
            if existing is None or latest_comment_at > existing:
                payload["latest_activity_at"] = latest_comment_at
    except Exception:
        logger.warning(
            "Unable to load comment activity for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    return payload


def _get_unprocessed_ticket_ids(session: Session) -> list[uuid.UUID]:
    return [
        row[0]
        for row in session.query(OperationalAnalysis.ticket_id)
        .filter(OperationalAnalysis.risk_processed == False)
        .distinct()
        .all()
    ]


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
        pending_ticket_ids = _get_unprocessed_ticket_ids(session)
        if ticket_uuid not in pending_ticket_ids:
            logger.info("Ticket already processed or no pending risk: %s", ticket_uuid)
            return None

        history = repository.get_ticket_history(ticket_uuid)
        if not history:
            logger.warning("No history found for ticket_id=%s", ticket_uuid)
            return None

        signals = _fetch_ticket_signals(session, ticket_uuid)
        result = compute(
            history,
            escalation_source=signals["escalation_source"],
            recommendation_source=signals["recommendation_source"],
            approval_action=signals["approval_action"],
            ai_confidences=signals["ai_confidences"],
            ticket_status=signals["ticket_status"],
            latest_activity_at=signals["latest_activity_at"],
        )
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


def process_pending_ticket_risks(db: Session | None = None) -> list[dict[str, Any] | None]:
    """Compute and persist risk for all tickets with unprocessed risk."""
    owns_session = db is None
    session = db or SessionLocal()
    results: list[dict[str, Any] | None] = []

    try:
        ticket_ids = _get_unprocessed_ticket_ids(session)
        for ticket_id in ticket_ids:
            results.append(process_ticket_risk(ticket_id, db=session))
        return results

    finally:
        if owns_session:
            session.close()
