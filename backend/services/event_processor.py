"""
services/event_processor.py
Event Ingestion Processor. Orchestrates the flow of incoming interaction events,
triggering database persistence, analysis, and metadata enrichment pipelines.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from repositories.interaction_repository import InteractionRepository
from schemas.event import EventCaptureRequest, EventCaptureResponse

logger = setup_logger(__name__)


def run_enrichment_task(operational_analysis_id_str: str) -> None:
    """Background task to run enrichment and downstream clustering for a record."""
    from db.session import SessionLocal
    from services.enrichment_orchestrator import EnrichmentOrchestrator

    logger.info("Starting background enrichment task for ID: %s", operational_analysis_id_str)
    db = SessionLocal()
    try:
        op_id = uuid.UUID(operational_analysis_id_str)
        # Fetch the ticket_id associated with this operational analysis row to acquire the lock
        oa_first = db.query(OperationalAnalysis).filter_by(id=op_id).first()
        if not oa_first:
            logger.error("Background enrichment aborted — operational_analysis record not found for id=%s", op_id)
            return

        canonical_ticket_id = oa_first.ticket_id

        # Concurrency-Safe Advisory Lock
        import hashlib
        hasher = hashlib.sha256(str(canonical_ticket_id).encode('utf-8'))
        lock_key = int.from_bytes(hasher.digest()[:8], byteorder='big', signed=True)

        # Acquire lock
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

        # Reload the canonical operational_analysis row inside the lock
        db.expire(oa_first)
        oa = db.query(OperationalAnalysis).filter_by(id=op_id).first()
        if not oa:
            logger.error("Background enrichment aborted — operational_analysis record disappeared for id=%s", op_id)
            return

        orchestrator = EnrichmentOrchestrator(db)
        orchestrator.enrich_interaction(op_id)
    except Exception as e:
        db.rollback()
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
            "Event received: ticket_id=%s",
            request.ticket_id,
        )

        try:
            # 1. Resolve parent ticket and sub-ticket
            sub_ticket_row = self._db.execute(
                text("SELECT ticket_id FROM sub_tickets WHERE id = :id"),
                {"id": request.ticket_id}
            ).mappings().first()

            if sub_ticket_row:
                canonical_ticket_id = sub_ticket_row["ticket_id"]
                if not canonical_ticket_id:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Sub-ticket {request.ticket_id} has no associated main ticket.",
                    )
            else:
                ticket_row = self._db.execute(
                    text("SELECT id FROM tickets WHERE id = :id"),
                    {"id": request.ticket_id}
                ).mappings().first()
                if not ticket_row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Ticket {request.ticket_id} not found in database.",
                    )
                canonical_ticket_id = ticket_row["id"]

            # 2. Concurrency-Safe Advisory Lock Key
            import hashlib
            hasher = hashlib.sha256(str(canonical_ticket_id).encode('utf-8'))
            lock_key = int.from_bytes(hasher.digest()[:8], byteorder='big', signed=True)

            # Acquire lock (held for the duration of this capture transaction)
            self._db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

            # 3. Retrieve operational_analysis rows for this canonical_ticket_id
            rows = self._db.query(OperationalAnalysis).filter_by(ticket_id=canonical_ticket_id).all()

            record = None
            if rows:
                # Sort deterministically:
                # 1. risk_processed (True first)
                # 2. captured_at desc (latest first)
                # 3. id asc (alphanumeric tie-breaker)
                def sort_key(oa):
                    proc = -1 if oa.risk_processed else 0
                    ts = -(oa.captured_at.timestamp() if oa.captured_at else 0)
                    return (proc, ts, str(oa.id))

                sorted_rows = sorted(rows, key=sort_key)
                record = sorted_rows[0]
                logger.info("Selected existing canonical operational analysis record: id=%s", record.id)
            else:
                # Resolve customer_id from tickets
                ticket_creator_row = self._db.execute(
                    text("SELECT created_by FROM tickets WHERE id = :id"),
                    {"id": canonical_ticket_id}
                ).mappings().first()
                customer_id = ticket_creator_row["created_by"] if ticket_creator_row else None

                # Create new record
                record = OperationalAnalysis(
                    ticket_id=canonical_ticket_id,
                    customer_id=customer_id,
                    risk_processed=False
                )
                self._db.add(record)
                self._db.flush()
                self._db.refresh(record)
                logger.info("Created new canonical operational analysis record: id=%s", record.id)

            # Commit the transaction (releases the advisory lock)
            self._db.commit()

            operational_id = str(record.id)

            # Automatically trigger enrichment in background or synchronously
            if background_tasks is not None:
                logger.info("Enqueuing background enrichment task for id=%s", operational_id)
                background_tasks.add_task(run_enrichment_task, operational_id)
            else:
                logger.info("Running enrichment task synchronously for id=%s", operational_id)
                try:
                    run_enrichment_task(operational_id)
                except Exception as enrichment_exc:
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
                "Unexpected error while capturing event for ticket_id=%s",
                request.ticket_id,
            )
            raise


