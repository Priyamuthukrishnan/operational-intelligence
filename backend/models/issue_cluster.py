"""
models/issue_cluster.py
SQLAlchemy database model representing ML-generated issue/topic clusters and category centroid references.
"""

import uuid
from datetime import datetime
from sqlalchemy import Integer, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from db.base_class import Base

class RootCauseTaxonomy(Base):
    """SQLAlchemy model representing the root cause taxonomy."""

    __tablename__ = "root_cause_taxonomy"

    category: Mapped[str] = mapped_column(Text, primary_key=True, comment="Primary key category name")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class IssueCluster(Base):
    """SQLAlchemy model representing ML-generated issue/topic clusters.

    Stores aggregated metrics and references for semantic groups of tickets.
    """

    __tablename__ = "issue_clusters"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Primary key UUID for the cluster",
    )
    cluster_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_category: Mapped[str | None] = mapped_column(Text, ForeignKey("root_cause_taxonomy.category"), nullable=True, index=True)
    frequency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
