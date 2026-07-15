"""
schemas/clustering.py
Pydantic validation schemas for customer groups, topic cluster stats, and repeat issue indicators.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Repeat Pattern Metadata ─────────────────────────────────────────────


class RepeatPatternMetadata(BaseModel):
    """Aggregated metadata for repeat-issue detection.

    Contains summary statistics derived from the customer's interaction
    history. No pattern-matching algorithm is applied — this is a pure
    data aggregation structure.
    """

    total_interactions: int = Field(
        ..., description="Total number of interaction records for the customer"
    )
    distinct_ticket_count: int = Field(
        ..., description="Number of distinct tickets associated with the customer"
    )
    distinct_categories: list[str] = Field(
        default_factory=list,
        examples=[],
        description="Distinct root-cause categories found (excludes None values)",
    )
    earliest_interaction: Optional[datetime] = Field(
        None, description="Timestamp of the earliest captured interaction"
    )
    latest_interaction: Optional[datetime] = Field(
        None, description="Timestamp of the most recent captured interaction"
    )
    repeat_count: int = Field(
        default=0,
        description=(
            "Number of interactions involved in repeat-issue patterns "
            "(derived from vector similarity matches)"
        ),
    )
    repeated_issue_frequency: float = Field(
        default=0.0,
        description=(
            "Ratio of repeat interactions to total interactions "
            "(repeat_count / total_interactions)"
        ),
    )

    @field_validator("distinct_categories", mode="before", check_fields=False)
    @classmethod
    def validate_distinct_categories(cls, v: Any) -> Any:
        if isinstance(v, list):
            from utils.scoring import normalize_category_name
            return [normalize_category_name(item) for item in v if item is not None]
        return v


# ── Similarity Search Results ────────────────────────────────────────────

class SimilarInteraction(BaseModel):
    """A single similarity match returned from Qdrant."""

    interaction_id: str = Field(
        ..., description="Qdrant point ID of the matched interaction"
    )
    similarity_score: float = Field(
        ..., description="Cosine similarity score from Qdrant scaled 0-10"
    )
    payload: Optional[dict[str, Any]] = Field(
        default=None,
        description="Qdrant point payload (metadata attached to the vector)",
    )


class SimilarityGroup(BaseModel):
    """A group of interactions similar to a source interaction."""

    source_interaction_id: uuid.UUID = Field(
        ..., description="Primary key of the source OperationalAnalysis record"
    )
    source_vector_id: str = Field(
        ..., description="qdrant_vector_id used for the similarity search"
    )
    similar_interactions: list[SimilarInteraction] = Field(
        default_factory=list,
        description="List of similar interactions found in Qdrant",
    )
    group_size: int = Field(
        ..., description="Number of similar interactions in this group"
    )
    similarity_score: Optional[float] = Field(
        None,
        description="Average similarity score across matches in this group scaled 0-10",
    )


class RepeatIssueDetail(BaseModel):
    """Repeat-issue frequency metadata for a similarity group."""

    source_interaction_id: uuid.UUID = Field(
        ..., description="Primary key of the source interaction"
    )
    source_vector_id: str = Field(
        ..., description="qdrant_vector_id used for detection"
    )
    occurrence_count: int = Field(
        ..., description="Number of similar occurrences found"
    )
    similarity_scores: list[float] = Field(
        default_factory=list,
        examples=[],
        description="Individual similarity scores of each occurrence scaled 0-10",
    )
    similarity_score: Optional[float] = Field(
        None, description="Average similarity across occurrences scaled 0-10"
    )


# ── Customer Cluster Summary ────────────────────────────────────────────


class CustomerClusterSummary(BaseModel):
    """Customer-level aggregation of interaction patterns and repeat metrics."""

    customer_id: uuid.UUID = Field(
        ..., description="The customer identifier"
    )
    total_interactions: int = Field(
        ..., description="Total interaction records for this customer"
    )
    distinct_ticket_count: int = Field(
        ..., description="Number of distinct tickets"
    )
    repeat_count: int = Field(
        default=0,
        description="Number of interactions involved in repeat-issue patterns",
    )
    repeated_issue_frequency: float = Field(
        default=0.0,
        description="Ratio of repeat interactions to total interactions",
    )
    distinct_categories: list[str] = Field(
        default_factory=list,
        examples=[],
        description="Distinct root-cause categories found",
    )
    sentiment_score: Optional[float] = Field(
        None, description="Average sentiment score on a 0-10 scale"
    )
    risk_score: Optional[float] = Field(
        None, description="Average escalation risk score on a 0-10 scale"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="List of distinct ticket UUIDs for this customer",
    )

    @field_validator("distinct_categories", mode="before", check_fields=False)
    @classmethod
    def validate_distinct_categories(cls, v: Any) -> Any:
        if isinstance(v, list):
            from utils.scoring import normalize_category_name
            return [normalize_category_name(item) for item in v if item is not None]
        return v


# ── Issue Cluster Group ─────────────────────────────────────────────────


class IssueClusterGroup(BaseModel):
    """A semantically grouped cluster of similar issues."""

    cluster_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Persisted UUID of the issue cluster",
    )
    cluster_label: str = Field(
        ...,
        description="Cluster name representing the issue",
    )
    interaction_count: int = Field(
        ..., description="Number of interactions in this cluster"
    )
    occurrence_count: int = Field(
        ..., description="Total similarity match occurrences across cluster members"
    )
    similarity_score: Optional[float] = Field(
        None, description="Average similarity score within this cluster scaled 0-10"
    )
    root_cause_categories: list[str] = Field(
        default_factory=list,
        examples=[],
        description="Distinct root-cause categories found within this cluster",
    )
    interaction_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="Primary keys of interactions in this cluster",
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="Distinct ticket UUIDs involved in this cluster",
    )

    @field_validator("root_cause_categories", mode="before", check_fields=False)
    @classmethod
    def validate_root_cause_categories(cls, v: Any) -> Any:
        if isinstance(v, list):
            from utils.scoring import normalize_category_name
            return [normalize_category_name(item) for item in v if item is not None]
        return v


# ── Time-Based Clustering ───────────────────────────────────────────────


class TimeBucket(BaseModel):
    """A single time-period bucket containing grouped interactions."""

    period_label: str = Field(
        ...,
        description="Human-readable period identifier",
    )
    granularity: str = Field(
        ..., description="Time grouping level: 'daily', 'weekly', or 'monthly'"
    )
    interaction_count: int = Field(
        ..., description="Number of interactions in this time bucket"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="Distinct ticket UUIDs in this time bucket",
    )
    categories: list[str] = Field(
        default_factory=list,
        examples=[],
        description="Distinct root-cause categories in this time bucket",
    )
    has_repeat_issues: bool = Field(
        default=False,
        description="Whether repeat-issue patterns were detected in this time window",
    )

    @field_validator("categories", mode="before", check_fields=False)
    @classmethod
    def validate_categories(cls, v: Any) -> Any:
        if isinstance(v, list):
            from utils.scoring import normalize_category_name
            return [normalize_category_name(item) for item in v if item is not None]
        return v


class TimeClusterResult(BaseModel):
    """Container for time-based clustering results at a specific granularity."""

    granularity: str = Field(
        ..., description="Time grouping level: 'daily', 'weekly', or 'monthly'"
    )
    buckets: list[TimeBucket] = Field(
        default_factory=list,
        description="Time buckets containing grouped interactions",
    )
    total_periods: int = Field(
        ..., description="Number of distinct time periods with interactions"
    )


class RepeatIssueCluster(BaseModel):
    """A repeat-issue cluster of a customer consisting of a parent ticket and subtickets."""

    parent_interaction_id: uuid.UUID = Field(
        ..., description="The ID of the parent interaction"
    )
    parent_ticket_id: uuid.UUID = Field(
        ..., description="The ticket ID of the parent interaction"
    )
    interaction_count: int = Field(
        ..., description="Total count of interactions in this cluster"
    )
    subticket_count: int = Field(
        ..., description="Count of subtickets in this cluster"
    )
    interaction_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="All interaction UUIDs in the cluster in chronological order"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="All ticket UUIDs in the cluster in chronological order"
    )
    subticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        examples=[],
        description="Ticket UUIDs of all subtickets in the cluster"
    )
    first_seen: datetime = Field(
        ..., description="Timestamp of the earliest interaction in the cluster"
    )
    last_seen: datetime = Field(
        ..., description="Timestamp of the most recent interaction in the cluster"
    )
    similarity_score: float = Field(
        ..., description="Average similarity score scaled 0-10"
    )
    sentiment_score: Optional[float] = Field(
        None, description="Average sentiment score on a 0-10 scale"
    )
    risk_score: Optional[float] = Field(
        None, description="Average escalation risk score on a 0-10 scale"
    )


# ── Customer Clustering Response ─────────────────────────────────────────


class CustomerClusteringResponse(BaseModel):
    """Top-level response returned by the customer clustering endpoint."""

    customer_id: uuid.UUID = Field(
        ..., description="The queried customer identifier"
    )
    interaction_count: int = Field(
        ..., description="Total interaction records found for this customer"
    )
    cluster_count: int = Field(
        default=0,
        description="Number of similarity groups identified from Qdrant vectors",
    )
    clusters: list[SimilarityGroup] = Field(
        default_factory=list,
        description="Similarity groups derived from Qdrant nearest-neighbour search",
    )
    vectors_available: int = Field(
        default=0,
        description="Count of interactions that have a qdrant_vector_id",
    )
    vectors_missing: int = Field(
        default=0,
        description="Count of interactions that lack a qdrant_vector_id",
    )
    repeat_issues: list[RepeatIssueDetail] = Field(
        default_factory=list,
        description="Repeat-issue detection results based on vector similarity",
    )
    clustering_ready: bool = Field(
        ...,
        description="Whether all required enrichment dependencies are satisfied",
    )
    repeat_pattern_metadata: Optional[RepeatPatternMetadata] = Field(
        None, description="Aggregated repeat-issue statistics"
    )
    repeat_issue_clusters: list[RepeatIssueCluster] = Field(
        default_factory=list,
        description="Repeat issue clusters derived from chronological similarity matching",
    )

    # ── Phase 2: Customer, Issue, and Time-Based Clusters ────────────────

    customer_clusters: Optional[CustomerClusterSummary] = Field(
        default=None,
        description="Customer-level aggregation",
    )
    issue_clusters: list[IssueClusterGroup] = Field(
        default_factory=list,
        description="Semantically grouped issue clusters",
    )
    time_clusters: list[TimeClusterResult] = Field(
        default_factory=list,
        description="Time-based clustering results",
    )
    persisted: bool = Field(
        default=False,
        description="Indicates whether cluster mappings were persisted to DB",
    )

