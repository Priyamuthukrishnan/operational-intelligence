"""
services/event_processor.py
Event Ingestion Processor. Orchestrates the flow of incoming interaction events,
triggering database persistence, analysis, and metadata enrichment pipelines.
"""

from __future__ import annotations

from typing import Any, Optional
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from repositories.interaction_repository import InteractionRepository
from schemas.event import EventCaptureRequest, EventCaptureResponse

logger = setup_logger(__name__)


def run_enrichment_task(operational_analysis_id_str: str) -> None:
    """Background task to run enrichment and downstream clustering for a record."""
    import uuid
    from db.session import SessionLocal
    from services.enrichment_orchestrator import EnrichmentOrchestrator

    logger.info("Starting background enrichment task for ID: %s", operational_analysis_id_str)
    db = SessionLocal()
    try:
        op_id = uuid.UUID(operational_analysis_id_str)
        orchestrator = EnrichmentOrchestrator(db)
        orchestrator.enrich_interaction(op_id)
    except Exception as e:
        logger.exception("Background enrichment task failed for ID %s: %s", operational_analysis_id_str, e)
    finally:
        db.close()


class EventProcessor:
    """Service that processes inbound interaction events.

    Responsibilities:
    1. Map the validated request payload to the ORM model.
    2. Persist the record via the repository layer.
    3. Commit the transaction.
    4. Trigger the enrichment pipeline.
    5. Return a structured response with the generated identifier.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repository = InteractionRepository(db)

    def capture_event(
        self,
        request: EventCaptureRequest,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> EventCaptureResponse:
        """Process, persist, and trigger enrichment for an incoming interaction event.

        Args:
            request: A validated :class:`EventCaptureRequest` payload.
            background_tasks: Optional FastAPI BackgroundTasks for async execution.

        Returns:
            An :class:`EventCaptureResponse` containing the persisted
            record's ``operational_analysis_id``.

        Raises:
            Exception: Re-raises unexpected errors after rolling back the
                transaction and logging the failure.
        """
        logger.info(
            "Event received: ai_analysis_id=%s ticket_id=%s customer_id=%s",
            request.ai_analysis_id,
            request.ticket_id,
            request.customer_id,
        )

        try:
            # Map validated request fields to ORM model
            record = OperationalAnalysis(
                ai_analysis_id=request.ai_analysis_id,
                ticket_id=request.ticket_id,
                customer_id=request.customer_id,
                comment_id=request.comment_id,
                source_used=request.source_used,
                assigned_agent_id=request.assigned_agent_id,
                assigned_manager_id=request.assigned_manager_id,
                resolution_state=request.resolution_state,
                query_summary=request.query_summary,
                response_summary=request.response_summary,
                sentiment_label=request.sentiment_label,
                sentiment_score=request.sentiment_score,
                escalation_risk_score=request.escalation_risk_score,
                escalation_risk_band=request.escalation_risk_band,
                root_cause_category=request.root_cause_category,
                root_cause_confidence=request.root_cause_confidence,
                repeat_count=request.repeat_count,
                cluster_id=request.cluster_id,
                qdrant_vector_id=request.qdrant_vector_id,
                model_version=request.model_version,
            )

            # Persist via repository (flush + refresh inside)
            persisted = self._repository.create(record)

            # Commit the transaction
            self._db.commit()

            operational_id = str(persisted.id)

            logger.info(
                "Event persisted successfully: id=%s",
                operational_id,
            )

            # Automatically trigger enrichment
            if background_tasks is not None:
                logger.info("Enqueuing background enrichment task for id=%s", operational_id)
                background_tasks.add_task(run_enrichment_task, operational_id)
            else:
                logger.info("Running enrichment task synchronously for id=%s", operational_id)
                try:
                    run_enrichment_task(operational_id)
                except Exception as enrichment_exc:
                    # Log but do not fail the event capture if enrichment sync fails
                    logger.exception(
                        "Synchronous enrichment execution failed for id=%s",
                        operational_id,
                    )

            return EventCaptureResponse(
                status="success",
                message="Event captured successfully",
                operational_analysis_id=operational_id,
              )

        except Exception:
            self._db.rollback()
            logger.exception(
                "Unexpected error while capturing event: "
                "ai_analysis_id=%s ticket_id=%s",
                request.ai_analysis_id,
                request.ticket_id,
            )
            raise

