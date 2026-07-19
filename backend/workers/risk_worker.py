"""Event-driven worker for computing and persisting risk scores."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.logging import setup_logger
from db.session import SessionLocal
from intelligence.risk_scorer import compute
from models.operational_analysis import OperationalAnalysis
from repositories.interaction_repository import InteractionRepository

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
        "parent_ticket_id": None,
        "sub_ticket_count": 0,
        "occurrence_count": 1,
        "is_manager_escalated": False,
        "comment_count": 0,
        "follow_up_count": 0,
        "reassignment_count": 0,
        "priority": "MEDIUM",
        "due_at": None,
        "sla_breached": False,
        "initial_ai_confidence": None,
    }

    try:
        ticket_row = session.execute(
            text(
                """
                SELECT status, updated_at, priority, due_at
                FROM tickets
                WHERE id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if ticket_row is not None:
            payload["ticket_status"] = ticket_row.get("status")
            payload["latest_activity_at"] = ticket_row.get("updated_at")
            if ticket_row.get("priority"):
                payload["priority"] = ticket_row["priority"]
            if ticket_row.get("due_at"):
                payload["due_at"] = ticket_row["due_at"]
    except Exception:
        logger.warning(
            "Unable to load ticket metadata for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    # Sub-tickets & Parent Ticket Hierarchy
    try:
        parent_row = session.execute(
            text(
                """
                SELECT ticket_id
                FROM sub_tickets
                WHERE id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if parent_row is not None:
            payload["parent_ticket_id"] = parent_row.get("ticket_id")
    except Exception:
        pass

    try:
        sub_count_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS sub_count
                FROM sub_tickets
                WHERE ticket_id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if sub_count_row is not None:
            payload["sub_ticket_count"] = int(sub_count_row.get("sub_count") or 0)
    except Exception:
        pass

    if payload["parent_ticket_id"] is not None:
        payload["occurrence_count"] = max(2, payload["sub_ticket_count"] + 1)
    elif payload["sub_ticket_count"] > 0:
        payload["occurrence_count"] = 1 + payload["sub_ticket_count"]

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
            if row.get("source_used") is not None:
                payload["escalation_source"] = row["source_used"]
            if row.get("confidence_score") is not None:
                conf_val = float(row["confidence_score"])
                if payload["initial_ai_confidence"] is None:
                    payload["initial_ai_confidence"] = conf_val
                payload["ai_confidences"].append(conf_val)
    except Exception:
        logger.warning(
            "Unable to load ai_analysis signals for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    # Bypassed: recommendations table does not exist in production schema.
    payload["recommendation_source"] = None

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
            action = str(approval_row.get("action") or "").lower()
            payload["approval_action"] = approval_row.get("action")
            if action in {"escalated", "escalation_requested", "approved", "manager_review"}:
                payload["is_manager_escalated"] = True
    except Exception:
        logger.warning(
            "Unable to load approval history for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    try:
        comment_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS total_comments, MAX(created_at) AS latest_comment_at
                FROM comments
                WHERE ticket_id = :ticket_id
                """
            ),
            {"ticket_id": ticket_id},
        ).mappings().first()
        if comment_row is not None:
            payload["comment_count"] = int(comment_row.get("total_comments") or 0)
            latest_comment_at = comment_row.get("latest_comment_at")
            if latest_comment_at is not None:
                existing = payload["latest_activity_at"]
                if existing is None or latest_comment_at > existing:
                    payload["latest_activity_at"] = latest_comment_at
    except Exception:
        logger.warning(
            "Unable to load comment activity for ticket_id=%s", ticket_id,
            exc_info=True,
        )

    # Follow-up count: sub-ticket comments represent customer follow-up engagement
    if payload["sub_ticket_count"] > 0:
        try:
            sub_comment_row = session.execute(
                text(
                    """
                    SELECT COUNT(*) AS follow_up_comments
                    FROM sub_ticket_comments
                    WHERE sub_ticket_id IN (
                        SELECT id FROM sub_tickets WHERE ticket_id = :ticket_id
                    )
                    """
                ),
                {"ticket_id": ticket_id},
            ).mappings().first()
            if sub_comment_row is not None:
                payload["follow_up_count"] = max(
                    payload["follow_up_count"],
                    int(sub_comment_row.get("follow_up_comments") or 0),
                )
        except Exception:
            logger.warning(
                "Unable to load sub-ticket follow-up comments for ticket_id=%s", ticket_id,
                exc_info=True,
            )

    # Derive SLA breach status from due_at if not already set
    if not payload["sla_breached"] and payload["due_at"] is not None:
        try:
            due = payload["due_at"]
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            status = str(payload.get("ticket_status") or "").lower()
            if due < datetime.now(timezone.utc) and status not in {"resolved", "closed", "cancelled"}:
                payload["sla_breached"] = True
        except (TypeError, ValueError):
            pass

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
            signals=signals,
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
        logger.info("Saving OperationalAnalysis...")
        session.flush()
        logger.info("OperationalAnalysis saved successfully.")

        try:
            from services.aggregation_service import AggregationService
            aggregation_service = AggregationService(session)
            aggregation_service.generate_all_rollups()
            session.commit()
            logger.info("Transaction committed successfully.")
        except Exception as exc:
            session.rollback()
            logger.error("Risk worker rollup regeneration failed: %s", exc)
            raise exc

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
