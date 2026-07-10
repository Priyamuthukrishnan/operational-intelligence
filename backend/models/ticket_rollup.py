"""
models/ticket_rollup.py
SQLAlchemy database model representing ticket rollup summaries, aggregating daily/weekly historical indicators.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from db.base_class import Base


class TicketRollup(Base):
    """Ticket Rollup model.

    Stores daily, weekly, and monthly pre-computed dashboard statistics
    and trend metrics.
    """

    __tablename__ = "ticket_rollups"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Primary key UUID for the rollup record",
    )

    period_label = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Period identifier (e.g. '2026-06-23', '2026-W26', '2026-06')",
    )

    granularity = Column(
        String(20),
        nullable=False,
        index=True,
        comment="Rollup frequency: 'daily', 'weekly', or 'monthly'",
    )

    interaction_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total interaction events in the period",
    )

    ticket_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total unique tickets in the period",
    )

    resolved_ticket_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total unique resolved tickets in the period",
    )

    resolution_rate = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Resolved tickets to total tickets ratio",
    )

    average_sentiment = Column(
        Float,
        nullable=True,
        comment="Mean sentiment score for the period",
    )

    average_escalation_risk = Column(
        Float,
        nullable=True,
        comment="Mean escalation risk score for the period",
    )

    critical_escalation_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total interactions in 'critical' or 'high' risk bands",
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp when this rollup record was last generated",
    )

    def __repr__(self) -> str:
        return (
            f"<TicketRollup(id={self.id}, "
            f"period={self.period_label}, "
            f"granularity={self.granularity}, "
            f"interactions={self.interaction_count})>"
        )
