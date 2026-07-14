"""
models/issue_cluster.py
SQLAlchemy database model representing ML-generated issue/topic clusters and category centroid references.
"""

import uuid
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from db.base_class import Base

class RootCauseTaxonomy(Base):
    """SQLAlchemy model representing the root cause taxonomy."""

    __tablename__ = "root_cause_taxonomy"

    category = Column(Text, primary_key=True, comment="Primary key category name")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=True, default=True)
    created_at = Column(DateTime(timezone=True), nullable=True)

class IssueCluster(Base):
    """SQLAlchemy model representing ML-generated issue/topic clusters.

    Stores aggregated metrics and references for semantic groups of tickets.
    """

    __tablename__ = "issue_clusters"

    cluster_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Primary key UUID for the cluster",
    )
    cluster_name = Column(Text, nullable=True)
    issue_category = Column(Text, nullable=True)
    root_cause_category = Column(Text, ForeignKey("root_cause_taxonomy.category"), nullable=True, index=True)
    frequency_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
