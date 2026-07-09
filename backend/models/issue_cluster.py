"""
backend/models/issue_cluster.py
SQLAlchemy database model representing ML-generated issue/topic clusters and category centroid references.
"""

import uuid
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from backend.db.base_class import Base

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
