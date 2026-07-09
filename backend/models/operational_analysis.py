import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.db.base_class import Base


class OperationalAnalysis(Base):
    """Operational Intelligence analytics table."""

    __tablename__ = "operational_analysis"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Auto-generated UUID primary key",
    )

    ai_analysis_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    ticket_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    comment_id = Column(UUID(as_uuid=True), nullable=True)

    # Snapshot fields used by the risk escalation layer.
    source_used = Column(String(20), nullable=True)
    assigned_agent_id = Column(UUID(as_uuid=True), nullable=True)
    assigned_manager_id = Column(UUID(as_uuid=True), nullable=True)
    resolution_state = Column(String(20), nullable=True)

    query_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)

    sentiment_label = Column(Text, nullable=True)
    sentiment_score = Column(Float, nullable=True)

    escalation_risk_score = Column(Float, nullable=True)
    escalation_risk_band = Column(Text, nullable=True)

    root_cause_category = Column(Text, nullable=True)
    root_cause_confidence = Column(Float, nullable=True)

    repeat_count = Column(Integer, nullable=True)
    cluster_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    qdrant_vector_id = Column(Text, nullable=True)

    # Risk processing state.
    confidence_decay_score = Column(Float, nullable=True)
    momentum_score = Column(Float, nullable=True)
    risk_multiplier = Column(Float, nullable=True)
    risk_reason = Column(JSONB, nullable=True)
    risk_processed = Column(Boolean, default=False, nullable=False)

    model_version = Column(Text, nullable=True)
    captured_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="Timestamp automatically set when the record is created",
    )

    def __repr__(self) -> str:
        return (
            f"<(OperationalAnalysis("
            f"id={self.id}, "
            f"ticket={self.ticket_id}, "
            f"customer={self.customer_id})>"
        )
