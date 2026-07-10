"""
schemas/clustering.py
Pydantic validation schemas for customer groups, topic cluster stats, and repeat issue indicators.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Feature Placeholder ─────────────────────────────────────────────────


class ClusteringFeaturePlaceholder(BaseModel):
    """Represents the enrichment feature slots for a single interaction.

    Each field corresponds to an intelligence module output. Fields remain
    ``None`` until the respective upstream module populates them.
    """

    interaction_id: uuid.UUID = Field(
        ..., description="Primary key of the OperationalAnalysis record"
    )
    ticket_id: uuid.UUID = Field(
        ..., description="Source ticket identifier"
    )
    query_summary: Optional[str] = Field(
        None, description="AI-generated query summary (populated by Summarization Engine)"
    )
    response_summary: Optional[str] = Field(
        None, description="AI-generated response summary (populated by Summarization Engine)"
    )
    sentiment_label: Optional[str] = Field(
        None, description="Sentiment classification label (populated by Sentiment Engine)"
    )
    sentiment_score: Optional[float] = Field(
        None, description="Sentiment score (populated by Sentiment Engine)"
    )
    escalation_risk_score: Optional[float] = Field(
        None, description="Escalation risk probability (populated by Escalation Risk Engine)"
    )
    root_cause_category: Optional[str] = Field(
        None, description="Predicted root-cause category (populated by Root Cause Engine)"
    )
    qdrant_vector_id: Optional[str] = Field(
        None, description="Vector ID in Qdrant store (populated by Embedding Service)"
    )


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


# ── Similarity Search Results ────────────────────────────────────────────


class SimilarInteraction(BaseModel):
    """A single similarity match returned from Qdrant."""

    interaction_id: str = Field(
        ..., description="Qdrant point ID of the matched interaction"
    )
    similarity_score: float = Field(
        ..., description="Cosine similarity score from Qdrant"
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
    avg_similarity_score: Optional[float] = Field(
        None,
        description="Average similarity score across all matches in this group",
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
        description="Individual similarity scores of each occurrence",
    )
    avg_similarity: Optional[float] = Field(
        None, description="Average similarity across occurrences"
    )


# ── Customer Cluster Summary ────────────────────────────────────────────


class CustomerClusterSummary(BaseModel):
    """Customer-level aggregation of interaction patterns and repeat metrics.

    Provides a single consolidated view of a customer's interaction
    history, including repeat-issue frequency derived from similarity
    analysis.
    """

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
        description="Distinct root-cause categories found",
    )
    avg_sentiment_score: Optional[float] = Field(
        None, description="Average sentiment score across all interactions"
    )
    avg_escalation_risk: Optional[float] = Field(
        None, description="Average escalation risk score across all interactions"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="List of distinct ticket UUIDs for this customer",
    )


# ── Issue Cluster Group ─────────────────────────────────────────────────


class IssueClusterGroup(BaseModel):
    """A semantically grouped cluster of similar issues.

    Derived from Qdrant nearest-neighbour similarity search with
    Union-Find deduplication. The ``cluster_label`` is a temporary
    system-generated identifier, not a final business-readable name.
    """

    cluster_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Persisted UUID of the issue cluster",
    )
    cluster_label: str = Field(
        ...,
        description=(
            "Temporary system-generated label (e.g. 'issue_cluster_1'). "
            "Not a final business-readable cluster name."
        ),
    )
    interaction_count: int = Field(
        ..., description="Number of interactions in this cluster"
    )
    occurrence_count: int = Field(
        ..., description="Total similarity match occurrences across cluster members"
    )
    avg_similarity_score: Optional[float] = Field(
        None, description="Average similarity score within this cluster"
    )
    root_cause_categories: list[str] = Field(
        default_factory=list,
        description="Distinct root-cause categories found within this cluster",
    )
    interaction_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Primary keys of interactions in this cluster",
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Distinct ticket UUIDs involved in this cluster",
    )


# ── Time-Based Clustering ───────────────────────────────────────────────


class TimeBucket(BaseModel):
    """A single time-period bucket containing grouped interactions."""

    period_label: str = Field(
        ...,
        description=(
            "Human-readable period identifier "
            "(e.g. '2026-06-23', '2026-W26', '2026-06')"
        ),
    )
    granularity: str = Field(
        ..., description="Time grouping level: 'daily', 'weekly', or 'monthly'"
    )
    interaction_count: int = Field(
        ..., description="Number of interactions in this time bucket"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Distinct ticket UUIDs in this time bucket",
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Distinct root-cause categories in this time bucket",
    )
    has_repeat_issues: bool = Field(
        default=False,
        description="Whether repeat-issue patterns were detected in this time window",
    )


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
        ..., description="The ID of the parent interaction (the earliest occurrence of the issue)"
    )
    parent_ticket_id: uuid.UUID = Field(
        ..., description="The ticket ID of the parent interaction"
    )
    interaction_count: int = Field(
        ..., description="Total count of interactions in this cluster (parent + subtickets)"
    )
    subticket_count: int = Field(
        ..., description="Count of subtickets in this cluster (interaction_count - 1)"
    )
    interaction_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="All interaction UUIDs in the cluster in chronological order"
    )
    ticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="All ticket UUIDs in the cluster in chronological order"
    )
    subticket_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Ticket UUIDs of all subtickets in the cluster in chronological order"
    )
    first_seen: datetime = Field(
        ..., description="Timestamp of the earliest interaction in the cluster"
    )
    last_seen: datetime = Field(
        ..., description="Timestamp of the most recent interaction in the cluster"
    )
    avg_similarity_score: float = Field(
        ..., description="Average similarity score of the subtickets to the parent ticket"
    )
    avg_sentiment_score: Optional[float] = Field(
        None, description="Average sentiment score across all interactions in the cluster"
    )
    avg_escalation_risk: Optional[float] = Field(
        None, description="Average escalation risk score across all interactions in the cluster"
    )


# ── Customer Clustering Response ─────────────────────────────────────────


class CustomerClusteringResponse(BaseModel):
    """Top-level response returned by the customer clustering endpoint.

    All values are populated dynamically from the customer's interaction
    records, Qdrant similarity search results, and the current state of
    intelligence module outputs.
    """

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
        description=(
            "Similarity groups derived from Qdrant nearest-neighbour search. "
            "Populated when qdrant_vector_id values are available."
        ),
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
        description=(
            "Repeat-issue detection results based on vector similarity. "
            "Each entry represents a source interaction with similar matches."
        ),
    )
    clustering_ready: bool = Field(
        ...,
        description=(
            "Whether all required enrichment dependencies are satisfied. "
            "Derived at runtime from the customer's interaction data."
        ),
    )
    pending_dependencies: list[str] = Field(
        default_factory=list,
        description=(
            "Intelligence modules whose outputs are still missing for at "
            "least one interaction. Computed dynamically — not a static list."
        ),
    )
    feature_placeholders: list[ClusteringFeaturePlaceholder] = Field(
        default_factory=list,
        description="Per-interaction enrichment feature state",
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
        description=(
            "Customer-level aggregation including repeat metrics, "
            "ticket summary, and average scores. Read-only analysis output."
        ),
    )
    issue_clusters: list[IssueClusterGroup] = Field(
        default_factory=list,
        description=(
            "Semantically grouped issue clusters derived from Qdrant "
            "similarity search with Union-Find deduplication. "
            "Read-only analysis output."
        ),
    )
    time_clusters: list[TimeClusterResult] = Field(
        default_factory=list,
        description=(
            "Time-based clustering results at daily, weekly, and monthly "
            "granularities. Read-only analysis output."
        ),
    )
    persisted: bool = Field(
        default=False,
        description="Indicates whether cluster mappings were persisted to DB",
    )

