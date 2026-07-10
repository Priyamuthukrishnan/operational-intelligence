"""
models/customer_health.py
SQLAlchemy database model representing customer health scores, trends, volumes, and metrics breakdown.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import UUID

from db.base_class import Base


class CustomerHealth(Base):
    """Customer Health model.

    Aggregates sentiment, risk, resolution, and repeat statistics to
    compute a composite customer health score.
    """

    __tablename__ = "customer_health"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Primary key UUID for the customer health record",
    )

    customer_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique identifier for the customer",
    )

    health_score = Column(
        Float,
        nullable=False,
        default=100.0,
        comment="Composite customer health score (0.0 to 100.0)",
    )

    sentiment_average = Column(
        Float,
        nullable=True,
        comment="Average sentiment score (-1.0 to 1.0)",
    )

    escalation_risk_average = Column(
        Float,
        nullable=True,
        comment="Average escalation risk score (0.0 to 1.0)",
    )

    repeat_issue_frequency = Column(
        Float,
        nullable=True,
        comment="Ratio of repeat interactions to total interactions",
    )

    resolution_rate = Column(
        Float,
        nullable=True,
        comment="Ratio of resolved tickets to total tickets",
    )

    interaction_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total customer interaction count",
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp when the customer health record was last updated",
    )

    def __repr__(self) -> str:
        return (
            f"<CustomerHealth(id={self.id}, "
            f"customer_id={self.customer_id}, "
            f"health_score={self.health_score})>"
        )
