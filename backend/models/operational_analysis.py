import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class OperationalAnalysis(Base):
    """Operational Intelligence analytics table."""

    __tablename__ = "operational_analysis"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Auto-generated UUID primary key",
    )

    ai_analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Snapshot fields used by the risk escalation layer.
    source_used: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolution_state: Mapped[str | None] = mapped_column(String(20), nullable=True)

    query_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    sentiment_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    escalation_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    escalation_risk_band: Mapped[str | None] = mapped_column(Text, nullable=True)

    root_cause_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    repeat_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    qdrant_vector_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Risk processing state.
    confidence_decay_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reason: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
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

