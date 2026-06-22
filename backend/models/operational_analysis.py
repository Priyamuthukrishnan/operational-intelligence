import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.db.base_class import Base

class OperationalAnalysis(Base):
    """Operational Intelligence analytics table.

    Stores every captured interaction event together with optional enrichment
    fields that are populated asynchronously by downstream intelligence
    modules (summarisation, sentiment, escalation risk, root-cause, etc.).
    """

    __tablename__ = "operational_analysis"

    # ── Primary key ──────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Auto-generated UUID primary key",
    )

    # ── Source identifiers (from Service Intelligence) ───────────────────
    ai_analysis_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    ticket_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    comment_id = Column(UUID(as_uuid=True), nullable=True)

    # ── Summarisation ────────────────────────────────────────────────────
    query_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)

    # ── Sentiment ────────────────────────────────────────────────────────
    sentiment_label = Column(String(50), nullable=True)
    sentiment_score = Column(Float, nullable=True)

    # ── Escalation risk ──────────────────────────────────────────────────
    escalation_risk_score = Column(Float, nullable=True)
    escalation_risk_band = Column(String(50), nullable=True)

    # ── Root cause ───────────────────────────────────────────────────────
    root_cause_category = Column(String(100), nullable=True)
    root_cause_confidence = Column(Float, nullable=True)

    # ── Clustering / embeddings ──────────────────────────────────────────
    repeat_count = Column(Integer, nullable=True)
    cluster_id = Column(UUID(as_uuid=True), nullable=True)
    qdrant_vector_id = Column(String(100), nullable=True)

    # ── Metadata ─────────────────────────────────────────────────────────
    model_version = Column(String(50), nullable=True)
    captured_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp automatically set when the record is created",
    )

    def __repr__(self) -> str:
        return (
            f"<(OperationalAnalysis("
            f"id={self.id}, "
            f"ticket={self.ticket_id}, "
            f"customer={self.customer_id})>"
        )
