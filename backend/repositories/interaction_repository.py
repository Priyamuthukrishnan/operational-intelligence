"""
backend/repositories/interaction_repository.py
Abstractions and database query wrappers for CRUD operations on interaction analytics models.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.logging import setup_logger
from backend.models.operational_analysis import OperationalAnalysis

logger = setup_logger(__name__)


class InteractionRepository:
    """Data-access layer for :class:`OperationalAnalysis` records.

    All methods are pure database operations — no business logic lives here.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Create ───────────────────────────────────────────────────────────

    def create(self, record: OperationalAnalysis) -> OperationalAnalysis:
        """Persist a new :class:`OperationalAnalysis` row and return it
        with database-generated defaults populated (PK, ``captured_at``).

        Args:
            record: A fully-populated (but uncommitted) model instance.

        Returns:
            The same instance after ``flush`` so that server defaults are
            visible.
        """
        self._db.add(record)
        self._db.flush()
        self._db.refresh(record)
        logger.info(
            "Persisted OperationalAnalysis record "
            "id=%s ticket_id=%s",
            record.id,
            record.ticket_id,
        )
        return record

    # ── Read ─────────────────────────────────────────────────────────────

    def get_by_id(
        self, id: uuid.UUID
    ) -> Optional[OperationalAnalysis]:
        """Fetch a single record by its primary key.

        Args:
            id: UUID of the record.

        Returns:
            The matching :class:`OperationalAnalysis` or ``None``.
        """
        return (
            self._db.query(OperationalAnalysis)
            .filter(
                OperationalAnalysis.id
                == id
            )
            .first()
        )

    def get_by_ticket_id(
        self, ticket_id: uuid.UUID
    ) -> list[OperationalAnalysis]:
        """Retrieve all analytics records for a given ticket.

        Args:
            ticket_id: The source ticket identifier.

        Returns:
            A list of matching records (may be empty).
        """
        return (
            self._db.query(OperationalAnalysis)
            .filter(OperationalAnalysis.ticket_id == ticket_id)
            .all()
        )

    # ── Update (future enrichment support) ───────────────────────────────

    def update(
        self,
        id: uuid.UUID,
        update_data: dict,
    ) -> Optional[OperationalAnalysis]:
        """Apply a partial update to an existing record.

        This method is intended for use by enrichment modules that
        populate fields asynchronously after initial capture.

        Args:
            id: UUID of the record to update.
            update_data: A dictionary of column names → new values.

        Returns:
            The updated record, or ``None`` if the ID was not found.
        """
        record = self.get_by_id(id)
        if record is None:
            logger.warning(
                "Update failed — record not found: id=%s",
                id,
            )
            return None

        for key, value in update_data.items():
            if hasattr(record, key):
                setattr(record, key, value)

        self._db.flush()
        self._db.refresh(record)
        logger.info(
            "Updated OperationalAnalysis record "
            "id=%s fields=%s",
            id,
            list(update_data.keys()),
        )
        return record
