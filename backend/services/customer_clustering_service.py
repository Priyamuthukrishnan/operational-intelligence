"""
services/customer_clustering_service.py
Customer Clustering Service. Orchestrates interaction retrieval, feature
preparation, repeat-pattern analysis, and Qdrant-powered similarity search.

Phase 1: Read-only Qdrant integration.
- Fetches vectors from Qdrant for interactions that have qdrant_vector_id.
- Runs nearest-neighbour similarity search.
- Returns similarity groups in the API response.
- Does NOT persist cluster_id to PostgreSQL.

Phase 2: Customer, Issue, and Time-Based Clustering.
- Customer-based clustering: groups interactions by customer_id with
  repeat metrics, average scores, and ticket summaries.
- Issue-based clustering: merges overlapping similarity groups via
  Union-Find deduplication into distinct issue clusters.
- Time-based clustering: groups interactions by captured_at into
  daily, weekly, and monthly buckets with repeat-issue detection.
- All Phase 2 output is read-only analysis — no data is persisted.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import get_settings
from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from repositories.cluster_repository import ClusterRepository
from utils.scoring import (
    convert_sentiment_score,
    convert_escalation_risk_score,
    convert_similarity_score,
)
from schemas.clustering import (
    CustomerClusteringResponse,
    CustomerClusterSummary,
    IssueClusterGroup,
    RepeatIssueCluster,
    RepeatIssueDetail,
    RepeatPatternMetadata,
    SimilarInteraction,
    SimilarityGroup,
    TimeBucket,
    TimeClusterResult,
)

logger = setup_logger(__name__)

from sqlalchemy import Table, Column, String
from sqlalchemy.dialects.postgresql import UUID
from db.base_class import Base

tickets_table = Table(
    "tickets",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("category", String(100)),
    Column("title", String(255)),
    Column("description", String(255)),
    extend_existing=True,
)

ai_analysis_table = Table(
    "ai_analysis",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("category_prediction", String(100)),
    extend_existing=True,
)

CATEGORY_NORMALIZATION = {
    "access_management": "Access Management",
    "service_outage": "Service Outage",
    "user_error": "User Error",
    "integration_failure": "Integration Failure",
    "software_bug": "Software Bug",
    "erp": "ERP",
    "finance": "Finance",
    "performance": "Performance",
    "reporting": "Reporting",
    "database": "Database",
    "network": "Network",
    "general_support": "General Support",
    "general support": "General Support",
}

SUBJECT_MAPPING = {
    "forgot password": "Password Reset Failures",
    "password reset": "Password Reset Failures",
    "password": "Password Reset and Login Failures",
    "login": "Password Reset and Login Failures",
    "signin": "Password Reset and Login Failures",
    "sign-in": "Password Reset and Login Failures",
    "wifi": "WiFi Access and Connectivity Failures",
    "wi-fi": "WiFi Access and Connectivity Failures",
    "blue screen": "Blue Screen Errors",
    "bsod": "Blue Screen Errors",
    "inventory": "Inventory Synchronization Failures",
    "overselling": "Inventory Synchronization Failures",
    "wms": "Inventory Synchronization Failures",
    "erp": "ERP Integration Failures",
    "invoice": "Invoice Tax Calculation Issues",
    "tax": "Invoice Tax Calculation Issues",
    "admin dashboard": "Admin Dashboard Access Issues",
    "dashboard": "Dashboard Access Issues",
    "access": "Access Authorization Issues",
    "permission": "Access Authorization Issues",
    "report": "Report Generation Failures",
    "reporting": "Report Generation Failures",
    "database": "Database Performance Issues",
    "sql": "Database Performance Issues",
    "query": "Database Performance Issues",
    "slow": "System Performance Degradation",
    "performance": "System Performance Degradation",
    "network": "Network Connection Failures",
    "connection": "Network Connection Failures",
    "outage": "Service Outage and Downtime",
    "down": "Service Outage and Downtime",
}

def _normalize_category(cat: str | None) -> str:
    if not cat:
        return "General Support"
    cat_clean = cat.strip().lower().replace("_", " ").replace("-", " ")
    if cat_clean in CATEGORY_NORMALIZATION:
        return CATEGORY_NORMALIZATION[cat_clean]
    
    cat_lower = cat.strip().lower()
    for k, v in CATEGORY_NORMALIZATION.items():
        if k.lower() == cat_lower:
            return v
            
    return cat.strip().title()


# ── Union-Find (Disjoint Set) for Issue Cluster Deduplication ────────────


class _UnionFind:
    """Lightweight Union-Find / Disjoint Set Union structure.

    Used to merge overlapping similarity groups so that bidirectional
    matches (A→B and B→A) are collapsed into a single issue cluster.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        """Find the root representative of the set containing ``x``."""
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])  # path compression
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        """Merge the sets containing ``x`` and ``y``."""
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x == root_y:
            return
        # Union by rank
        if self._rank[root_x] < self._rank[root_y]:
            self._parent[root_x] = root_y
        elif self._rank[root_x] > self._rank[root_y]:
            self._parent[root_y] = root_x
        else:
            self._parent[root_y] = root_x
            self._rank[root_x] += 1


class CustomerClusteringService:
    """Service layer for customer clustering operations.

    Responsibilities:
    1. Retrieve customer interactions via the repository layer.
    2. Prepare enrichment feature placeholders for future clustering.
    3. Aggregate repeat-pattern metadata from interaction history.
    4. Assess clustering readiness based on dependency availability.
    5. Fetch vectors from Qdrant and run similarity search (read-only).
    6. Detect repeat issues using vector similarity.
    7. Build customer-level cluster summaries.
    8. Build issue-level clusters via Union-Find deduplication.
    9. Build time-based clusters at daily, weekly, and monthly granularity.

    Qdrant integration is optional — if Qdrant is not configured, the
    service gracefully returns empty similarity results while preserving
    all existing scaffolding behaviour.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repository = ClusterRepository(db)
        self._settings = get_settings()

        # ── Initialise Qdrant service (optional) ─────────────────────────
        self._qdrant: Optional[Any] = None
        try:
            from services.qdrant_service import QdrantService

            self._qdrant = QdrantService()
            logger.info("Qdrant service initialised for clustering")
        except Exception as exc:
            logger.warning(
                "Qdrant service not available — similarity search "
                "will return empty results: %s",
                exc,
            )

    # ── Interaction Retrieval ────────────────────────────────────────────

    def get_customer_interactions(
        self, customer_id: uuid.UUID
    ) -> list[OperationalAnalysis]:
        """Retrieve all interaction records for a customer.

        Delegates to the repository layer for database access.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of :class:`OperationalAnalysis` records ordered by
            ``captured_at`` descending.
        """
        interactions = self._repository.get_by_customer_id(customer_id)
        logger.info(
            "Fetched %d interaction(s) for customer_id=%s",
            len(interactions),
            customer_id,
        )
        return interactions



    # ── Repeat Pattern Analysis ──────────────────────────────────────────

    def calculate_repeat_patterns(
        self,
        customer_id: uuid.UUID,
        repeat_issues: list[RepeatIssueDetail] | None = None,
    ) -> RepeatPatternMetadata:
        """Aggregate repeat-issue metadata from a customer's interaction history.

        Gathers summary statistics (counts, categories, time range) from
        the repository layer. When ``repeat_issues`` are provided, derives
        ``repeat_count`` and ``repeated_issue_frequency`` from the
        similarity-based detection results.

        Args:
            customer_id: UUID of the customer.
            repeat_issues: Optional list of repeat-issue detection results
                used to compute repeat metrics.

        Returns:
            A :class:`RepeatPatternMetadata` with aggregated statistics.
        """
        total_interactions = self._repository.get_customer_interaction_count(
            customer_id
        )
        categories = self._repository.get_customer_issue_categories(
            customer_id
        )

        # Compute distinct ticket count and time range from interaction records
        distinct_ticket_count = (
            self._db.query(
                func.count(func.distinct(OperationalAnalysis.ticket_id))
            )
            .filter(OperationalAnalysis.customer_id == customer_id)
            .scalar()
        ) or 0

        earliest_interaction = (
            self._db.query(func.min(OperationalAnalysis.captured_at))
            .filter(OperationalAnalysis.customer_id == customer_id)
            .scalar()
        )

        latest_interaction = (
            self._db.query(func.max(OperationalAnalysis.captured_at))
            .filter(OperationalAnalysis.customer_id == customer_id)
            .scalar()
        )

        # Derive repeat metrics from similarity-based detection (reflecting membership)
        repeat_count = 0
        repeated_issue_frequency = 0.0

        if repeat_issues:
            # Sum of memberships across all repeat issues (occurrence_count + 1)
            repeat_count = sum(issue.occurrence_count + 1 for issue in repeat_issues if issue.occurrence_count > 0)
            if total_interactions > 0:
                repeated_issue_frequency = round(
                    repeat_count / total_interactions, 4
                )

        metadata = RepeatPatternMetadata(
            total_interactions=total_interactions,
            distinct_ticket_count=distinct_ticket_count,
            distinct_categories=categories,
            earliest_interaction=earliest_interaction,
            latest_interaction=latest_interaction,
            repeat_count=repeat_count,
            repeated_issue_frequency=repeated_issue_frequency,
        )

        logger.info(
            "Calculated repeat patterns for customer_id=%s: "
            "interactions=%d tickets=%d categories=%d "
            "repeat_count=%d frequency=%.4f",
            customer_id,
            total_interactions,
            distinct_ticket_count,
            len(categories),
            repeat_count,
            repeated_issue_frequency,
        )
        return metadata

    # ── Qdrant Vector Retrieval ──────────────────────────────────────────

    def fetch_customer_vectors(
        self, customer_id: uuid.UUID
    ) -> list[dict]:
        """Fetch vectors from Qdrant for a customer's interactions.

        Queries the repository for interactions that have a
        ``qdrant_vector_id``, then batch-retrieves the actual vectors
        from Qdrant.  Missing vectors are logged and skipped.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of dicts, each containing::

                {
                    "interaction_id": uuid.UUID,
                    "vector_id": str,
                    "vector": list[float],
                    "payload": dict,
                }

            Only interactions whose vectors were successfully retrieved
            from Qdrant are included.
        """
        if self._qdrant is None:
            logger.warning(
                "Qdrant not available — cannot fetch vectors for "
                "customer_id=%s",
                customer_id,
            )
            return []

        # Step 1: Get interactions with vector IDs from PostgreSQL
        interactions = self._repository.get_interactions_with_vectors(
            customer_id
        )

        logger.info(
            "Fetched %d interaction(s) with vector IDs from PostgreSQL for customer_id=%s",
            len(interactions),
            customer_id
        )

        if not interactions:
            logger.info(
                "No interactions with qdrant_vector_id found for "
                "customer_id=%s",
                customer_id,
            )
            return []

        # Step 2: Batch-retrieve vectors from Qdrant
        vector_ids = [
            interaction.qdrant_vector_id for interaction in interactions
        ]
        qdrant_results = self._qdrant.get_vectors(vector_ids)

        logger.info(
            "Successfully retrieved %d vector(s) from Qdrant out of %d requested for customer_id=%s",
            len(qdrant_results),
            len(vector_ids),
            customer_id
        )

        # Build a lookup by Qdrant point ID for matching (normalized keys)
        qdrant_lookup = {
            str(result["id"]).lower().strip(): result for result in qdrant_results
        }

        # Step 3: Merge DB interactions with Qdrant vectors
        enriched = []
        for interaction in interactions:
            norm_db_vid = str(interaction.qdrant_vector_id).lower().strip()
            qdrant_data = qdrant_lookup.get(norm_db_vid)
            if qdrant_data is None and interaction.qdrant_vector_id is not None:
                # Try coerced ID lookup
                from services.qdrant_service import QdrantService

                coerced = str(
                    QdrantService._coerce_point_id(
                        interaction.qdrant_vector_id
                    )
                ).lower().strip()
                qdrant_data = qdrant_lookup.get(coerced)

            if qdrant_data and qdrant_data.get("vector"):
                enriched.append(
                    {
                        "interaction_id": interaction.id,
                        "vector_id": interaction.qdrant_vector_id,
                        "vector": qdrant_data["vector"],
                        "payload": qdrant_data.get("payload", {}),
                    }
                )
            else:
                logger.warning(
                    "Vector missing in Qdrant for interaction_id=%s "
                    "vector_id=%s",
                    interaction.id,
                    interaction.qdrant_vector_id,
                )

        logger.info(
            "Fetched %d/%d vectors from Qdrant for customer_id=%s",
            len(enriched),
            len(interactions),
            customer_id,
        )
        return enriched

    # ── Similarity Search ────────────────────────────────────────────────

    def find_similar_interactions(
        self, vector_id: str, vector: list[float], customer_id: Optional[Any] = None
    ) -> list[SimilarInteraction]:
        """Find interactions similar to a given vector.

        Performs nearest-neighbour search in Qdrant, filters out the
        self-match, and returns scored results.

        Args:
            vector_id: The Qdrant point ID of the source vector
                (used to exclude self-match).
            vector: The actual embedding vector to search with.
            customer_id: Optional customer UUID to filter matches.

        Returns:
            A list of :class:`SimilarInteraction` results sorted by
            descending similarity score.  Self-matches are excluded.
        """
        if self._qdrant is None:
            logger.warning("Qdrant service not initialized — find_similar_interactions returning empty")
            return []

        logger.info(
            "Executing Qdrant similarity search with source vector_id=%s customer_id=%s",
            vector_id,
            customer_id,
        )

        raw_results = self._qdrant.search_similar(
            vector=vector,
            limit=self._settings.SIMILARITY_SEARCH_LIMIT,
            score_threshold=self._settings.SIMILARITY_THRESHOLD,
            customer_id=customer_id,
        )

        logger.info(
            "Qdrant similarity search returned %d match(es) for vector_id=%s",
            len(raw_results),
            vector_id
        )

        # Filter out self-match using normalized string comparison
        similar = []
        norm_source_id = vector_id.lower().strip()
        for result in raw_results:
            norm_match_id = str(result["id"]).lower().strip()
            
            logger.info(
                "Inspecting match point_id=%s with similarity score=%.4f (norm_match_id=%s, norm_source_id=%s)",
                result["id"],
                result["score"],
                norm_match_id,
                norm_source_id
            )
            
            if norm_match_id == norm_source_id:
                logger.info(
                    "Skipping match point_id=%s (score=%.4f) because it matches the source vector (self-match)",
                    result["id"],
                    result["score"]
                )
                continue

            # 1. Payload validation
            payload = result.get("payload") or {}
            match_cust_id = payload.get("customer_id")
            if customer_id is not None and match_cust_id:
                if str(match_cust_id).lower().strip() != str(customer_id).lower().strip():
                    logger.warning(
                        "Payload Customer validation failed for matched vector %s: %s != %s",
                        result["id"],
                        match_cust_id,
                        customer_id
                    )
                    continue

            # 2. Database level validation
            if customer_id is not None:
                oa_match = self._db.query(OperationalAnalysis.id).filter(
                    OperationalAnalysis.qdrant_vector_id == result["id"],
                    OperationalAnalysis.customer_id == customer_id
                ).first()
                if not oa_match:
                    logger.warning(
                        "DB Customer validation failed for matched vector %s: does not belong to customer %s in PostgreSQL",
                        result["id"],
                        customer_id
                    )
                    continue

            similar.append(
                SimilarInteraction(
                    interaction_id=result["id"],
                    similarity_score=convert_similarity_score(result["score"]) or 0.0,
                    payload=result.get("payload"),
                )
            )

        logger.debug(
            "Found %d similar interaction(s) for vector_id=%s "
            "(threshold=%.3f)",
            len(similar),
            vector_id,
            self._settings.SIMILARITY_THRESHOLD,
        )
        return similar

    # ── Similarity Group Builder ─────────────────────────────────────────

    def build_similarity_groups(
        self, customer_id: uuid.UUID, enriched_vectors: Optional[list[dict]] = None
    ) -> list[SimilarityGroup]:
        """Build similarity groups for a customer's interactions.

        For each interaction that has a vector in Qdrant, performs
        similarity search and assembles the results into groups.

        Args:
            customer_id: UUID of the customer.
            enriched_vectors: Optional pre-fetched vector list to avoid double-fetching.

        Returns:
            A list of :class:`SimilarityGroup`, one per interaction
            that has at least one similar match.
        """
        if enriched_vectors is None:
            enriched_vectors = self.fetch_customer_vectors(customer_id)

        if not enriched_vectors:
            logger.info(
                "No vectors available for similarity grouping: "
                "customer_id=%s",
                customer_id,
            )
            return []

        groups: list[SimilarityGroup] = []

        for entry in enriched_vectors:
            similar = self.find_similar_interactions(
                vector_id=entry["vector_id"],
                vector=entry["vector"],
                customer_id=customer_id,
            )

            if not similar:
                continue

            scores = [s.similarity_score for s in similar]
            avg_score = sum(scores) / len(scores) if scores else None

            group = SimilarityGroup(
                source_interaction_id=entry["interaction_id"],
                source_vector_id=entry["vector_id"],
                similar_interactions=similar,
                group_size=len(similar),
                similarity_score=round(avg_score, 2) if avg_score is not None else None,
            )
            groups.append(group)

        logger.info(
            "Built %d similarity group(s) for customer_id=%s",
            len(groups),
            customer_id,
        )
        return groups


    # ── Phase 2: Customer-Based Clustering ───────────────────────────────

    def build_customer_cluster(
        self,
        customer_id: uuid.UUID,
        interactions: list[OperationalAnalysis],
        repeat_issues: list[RepeatIssueDetail],
    ) -> CustomerClusterSummary:
        """Build a customer-level cluster summary.

        Aggregates all interactions for a customer into a single
        consolidated view with repeat metrics, average scores, and
        ticket identifiers. This is a read-only analysis — no data
        is written to PostgreSQL.

        Args:
            customer_id: UUID of the customer.
            interactions: Pre-fetched interaction records.
            repeat_issues: Pre-computed repeat-issue detection results.

        Returns:
            A :class:`CustomerClusterSummary` with aggregated metrics.
        """
        total_interactions = len(interactions)

        # Distinct ticket IDs from repository
        ticket_ids = self._repository.get_distinct_ticket_ids(customer_id)
        distinct_ticket_count = len(ticket_ids)

        # Distinct root-cause categories (exclude None)
        distinct_categories = list(
            {
                i.root_cause_category
                for i in interactions
                if i.root_cause_category is not None
            }
        )

        # Repeat count from similarity detection (reflecting membership)
        repeat_count = sum(issue.occurrence_count + 1 for issue in repeat_issues if issue.occurrence_count > 0)

        repeated_issue_frequency = 0.0
        if total_interactions > 0:
            repeated_issue_frequency = round(
                repeat_count / total_interactions, 4
            )

        # Average scores from repository (handles None exclusion)
        avg_sentiment = self._repository.get_customer_sentiment_avg(
            customer_id
        )
        avg_escalation = self._repository.get_customer_escalation_risk_avg(
            customer_id
        )

        summary = CustomerClusterSummary(
            customer_id=customer_id,
            total_interactions=total_interactions,
            distinct_ticket_count=distinct_ticket_count,
            repeat_count=repeat_count,
            repeated_issue_frequency=repeated_issue_frequency,
            distinct_categories=distinct_categories,
            sentiment_score=convert_sentiment_score(avg_sentiment),
            risk_score=convert_escalation_risk_score(avg_escalation),
            ticket_ids=ticket_ids,
        )

        logger.info(
            "Built customer cluster for customer_id=%s: "
            "interactions=%d tickets=%d repeat=%d frequency=%.4f",
            customer_id,
            total_interactions,
            distinct_ticket_count,
            repeat_count,
            repeated_issue_frequency,
        )
        return summary

    # ── Phase 2: Issue-Based Clustering (Union-Find) ─────────────────────

    def build_issue_clusters(
        self,
        interactions: list[OperationalAnalysis],
        similarity_groups: list[SimilarityGroup],
    ) -> list[IssueClusterGroup]:
        """Build deduplicated issue clusters from similarity groups.

        Uses Union-Find to merge overlapping similarity groups so that
        bidirectional matches (A→B and B→A) form a single cluster.
        Maps Qdrant point IDs back to OperationalAnalysis records to
        populate interaction-level metadata.

        This is a read-only analysis — no data is written to PostgreSQL.

        Args:
            interactions: Pre-fetched interaction records for the customer.
            similarity_groups: Pre-computed similarity groups from Qdrant.

        Returns:
            A list of :class:`IssueClusterGroup` with deduplicated
            cluster memberships.
        """
        if not similarity_groups:
            return []

        # Build lookup: qdrant_vector_id → OperationalAnalysis record (normalized keys)
        vector_to_interaction: dict[str, OperationalAnalysis] = {}
        for interaction in interactions:
            if interaction.qdrant_vector_id is not None:
                norm_key = interaction.qdrant_vector_id.lower().strip()
                vector_to_interaction[norm_key] = interaction

        # Union-Find: merge overlapping similarity groups using normalized keys
        uf = _UnionFind()
        all_scores: dict[str, list[float]] = defaultdict(list)

        for group in similarity_groups:
            source_vid = group.source_vector_id.lower().strip()
            for match in group.similar_interactions:
                matched_vid = match.interaction_id.lower().strip()
                uf.union(source_vid, matched_vid)
                all_scores[source_vid].append(match.similarity_score)
                all_scores[matched_vid].append(match.similarity_score)

        # Group vector IDs by their Union-Find root
        clusters_map: dict[str, set[str]] = defaultdict(set)
        all_vids = set()
        for group in similarity_groups:
            all_vids.add(group.source_vector_id.lower().strip())
            for match in group.similar_interactions:
                all_vids.add(match.interaction_id.lower().strip())

        for vid in all_vids:
            root = uf.find(vid)
            clusters_map[root].add(vid)

        # Build IssueClusterGroup for each merged cluster
        issue_clusters: list[IssueClusterGroup] = []
        cluster_index = 0

        for root, member_vids in sorted(
            clusters_map.items(), key=lambda x: len(x[1]), reverse=True
        ):
            cluster_index += 1

            interaction_ids: list[uuid.UUID] = []
            ticket_ids_set: set[uuid.UUID] = set()
            categories_set: set[str] = set()
            cluster_scores: list[float] = []

            for vid in member_vids:
                # Collect similarity scores for this cluster
                cluster_scores.extend(all_scores.get(vid, []))

                # Map vector ID back to interaction record
                interaction = vector_to_interaction.get(vid)
                if interaction is not None:
                    interaction_ids.append(interaction.id)
                    ticket_ids_set.add(interaction.ticket_id)
                    if interaction.root_cause_category is not None:
                        categories_set.add(interaction.root_cause_category)

            avg_score = None
            if cluster_scores:
                avg_score = round(
                    sum(cluster_scores) / len(cluster_scores), 4
                )

            issue_cluster = IssueClusterGroup(
                cluster_label=f"issue_cluster_{cluster_index}",
                interaction_count=len(interaction_ids),
                occurrence_count=len(cluster_scores),
                similarity_score=avg_score,
                root_cause_categories=sorted(categories_set),
                interaction_ids=interaction_ids,
                ticket_ids=sorted(ticket_ids_set),
            )
            issue_clusters.append(issue_cluster)

        logger.info(
            "Built %d issue cluster(s) from %d similarity group(s)",
            len(issue_clusters),
            len(similarity_groups),
        )
        return issue_clusters

    # ── Phase 2: Time-Based Clustering ───────────────────────────────────

    def build_time_clusters(
        self,
        interactions: list[OperationalAnalysis],
        repeat_issues: list[RepeatIssueDetail],
    ) -> list[TimeClusterResult]:
        """Build time-based clusters at daily, weekly, and monthly granularity.

        Groups interactions by their ``captured_at`` timestamp into
        time buckets. Each bucket includes interaction count, ticket IDs,
        root-cause categories, and whether repeat-issue patterns were
        detected within the time window.

        The ``TIME_CLUSTER_MIN_INTERACTIONS`` setting controls the
        minimum number of interactions required for a bucket to be
        included in the results.

        This is a read-only analysis — no data is written to PostgreSQL.

        Args:
            interactions: Pre-fetched interaction records for the customer.
            repeat_issues: Pre-computed repeat-issue detection results.

        Returns:
            A list of :class:`TimeClusterResult`, one per granularity
            (daily, weekly, monthly).
        """
        if not interactions:
            return []

        min_interactions = self._settings.TIME_CLUSTER_MIN_INTERACTIONS

        # Collect interaction IDs involved in repeat issues
        repeat_interaction_ids: set[uuid.UUID] = set()
        for issue in repeat_issues:
            if issue.occurrence_count > 0:
                repeat_interaction_ids.add(issue.source_interaction_id)

        # Define key-extraction functions for each granularity
        def _daily_key(interaction: OperationalAnalysis) -> str:
            if interaction.captured_at is None:
                return "unknown"
            return interaction.captured_at.date().isoformat()

        def _weekly_key(interaction: OperationalAnalysis) -> str:
            if interaction.captured_at is None:
                return "unknown"
            return interaction.captured_at.strftime("%G-W%V")

        def _monthly_key(interaction: OperationalAnalysis) -> str:
            if interaction.captured_at is None:
                return "unknown"
            return interaction.captured_at.strftime("%Y-%m")

        granularities = [
            ("daily", _daily_key),
            ("weekly", _weekly_key),
            ("monthly", _monthly_key),
        ]

        time_cluster_results: list[TimeClusterResult] = []

        for granularity_name, key_fn in granularities:
            # Group interactions by time key
            buckets_map: dict[str, list[OperationalAnalysis]] = defaultdict(
                list
            )
            for interaction in interactions:
                key = key_fn(interaction)
                buckets_map[key].append(interaction)

            # Build TimeBucket for each period
            buckets: list[TimeBucket] = []
            for period_label in sorted(buckets_map.keys()):
                bucket_interactions = buckets_map[period_label]

                if len(bucket_interactions) < min_interactions:
                    continue

                # Distinct ticket IDs in this bucket
                bucket_ticket_ids = sorted(
                    {i.ticket_id for i in bucket_interactions}
                )

                # Distinct root-cause categories (exclude None)
                bucket_categories = sorted(
                    {
                        i.root_cause_category
                        for i in bucket_interactions
                        if i.root_cause_category is not None
                    }
                )

                # Check for repeat issues in this time window
                has_repeat = any(
                    i.id in repeat_interaction_ids
                    for i in bucket_interactions
                )

                bucket = TimeBucket(
                    period_label=period_label,
                    granularity=granularity_name,
                    interaction_count=len(bucket_interactions),
                    ticket_ids=bucket_ticket_ids,
                    categories=bucket_categories,
                    has_repeat_issues=has_repeat,
                )
                buckets.append(bucket)

            result = TimeClusterResult(
                granularity=granularity_name,
                buckets=buckets,
                total_periods=len(buckets),
            )
            time_cluster_results.append(result)

        logger.info(
            "Built time clusters: %s",
            {r.granularity: r.total_periods for r in time_cluster_results},
        )
        return time_cluster_results

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Calculate the cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm_v1 = sum(a * a for a in v1) ** 0.5
        norm_v2 = sum(b * b for b in v2) ** 0.5
        if norm_v1 == 0.0 or norm_v2 == 0.0:
            return 0.0
        return dot_product / (norm_v1 * norm_v2)

    def build_repeat_issue_clusters(
        self,
        customer_id: uuid.UUID,
        interactions: list[OperationalAnalysis],
        enriched_vectors: Optional[list[dict]] = None,
    ) -> list[RepeatIssueCluster]:
        """Build Customer Repeat-Issue (Parent Ticket / Subticket) Clusters.

        Rules:
        - Earliest ticket for a customer issue becomes the parent ticket.
        - Later semantically similar tickets from the same customer become subtickets.
        - If no repeated similar ticket exists, repeat_issue_clusters should be empty.
        - Same customer with unrelated issues should create separate parent groups internally
          but should not appear as repeat_issue_clusters unless a group has more than one interaction.
        """
        # Step 1: Fetch Qdrant vectors for the customer's interactions
        if enriched_vectors is None:
            enriched_vectors = self.fetch_customer_vectors(customer_id)
        vector_map: dict[uuid.UUID, list[float]] = {
            v["interaction_id"]: v["vector"] for v in enriched_vectors if "vector" in v and v["vector"] is not None
        }

        # Step 2: Sort interactions by captured_at ascending (chronologically)
        sorted_interactions = sorted(
            interactions,
            key=lambda x: x.captured_at if x.captured_at is not None else datetime.min.replace(tzinfo=timezone.utc),
        )

        # Step 3: Process chronologically
        groups: list[dict] = []
        similarity_threshold = self._settings.SIMILARITY_THRESHOLD

        for interaction in sorted_interactions:
            interaction_vector = vector_map.get(interaction.id)

            matched_group = None
            max_sim = -1.0

            if interaction_vector is not None:
                # Compare against previously discovered Parent Tickets
                for group in groups:
                    parent_interaction = group["parent"]
                    parent_vector = vector_map.get(parent_interaction.id)
                    if parent_vector is not None:
                        sim = self._cosine_similarity(interaction_vector, parent_vector)
                        if sim > max_sim:
                            max_sim = sim
                            matched_group = group

            if matched_group is not None and max_sim >= similarity_threshold:
                # Attach interaction to the matching Parent Ticket as a Subticket
                matched_group["subtickets"].append(interaction)
                matched_group["similarities"].append(max_sim)
            else:
                # Create a new Parent Ticket group
                groups.append({
                    "parent": interaction,
                    "subtickets": [],
                    "similarities": []
                })

        # Step 4: Build Parent/Subticket clusters where interaction_count > 1
        repeat_issue_clusters = []
        for group in groups:
            parent = group["parent"]
            subtickets = group["subtickets"]
            similarities = group["similarities"]
            interaction_count = 1 + len(subtickets)

            if interaction_count > 1:
                # Calculate averages
                sentiment_scores = [
                    i.sentiment_score
                    for i in [parent] + subtickets
                    if i.sentiment_score is not None
                ]
                avg_sentiment = (
                    sum(sentiment_scores) / len(sentiment_scores)
                    if sentiment_scores
                    else None
                )

                escalation_risks = [
                    i.escalation_risk_score
                    for i in [parent] + subtickets
                    if i.escalation_risk_score is not None
                ]
                avg_escalation = (
                    sum(escalation_risks) / len(escalation_risks)
                    if escalation_risks
                    else None
                )

                avg_similarity = (
                    sum(similarities) / len(similarities)
                    if similarities
                    else 0.0
                )

                # Date bounds
                captured_dates = [
                    i.captured_at
                    for i in [parent] + subtickets
                    if i.captured_at is not None
                ]
                first_seen = min(captured_dates) if captured_dates else parent.captured_at
                last_seen = max(captured_dates) if captured_dates else parent.captured_at

                cluster = RepeatIssueCluster(
                    parent_interaction_id=parent.id,
                    parent_ticket_id=parent.ticket_id,
                    interaction_count=interaction_count,
                    subticket_count=len(subtickets),
                    interaction_ids=[parent.id] + [sub.id for sub in subtickets],
                    ticket_ids=[parent.ticket_id] + [sub.ticket_id for sub in subtickets],
                    subticket_ids=[sub.ticket_id for sub in subtickets],
                    first_seen=first_seen,
                    last_seen=last_seen,
                    similarity_score=convert_similarity_score(avg_similarity) or 0.0,
                    sentiment_score=convert_sentiment_score(avg_sentiment),
                    risk_score=convert_escalation_risk_score(avg_escalation),
                )
                repeat_issue_clusters.append(cluster)

        return repeat_issue_clusters

    # ── Clustering Orchestration ─────────────────────────────────────────

    def group_customer_issues(
        self, customer_id: uuid.UUID
    ) -> CustomerClusteringResponse:
        """Orchestrate clustering and similarity analysis for a customer.

        Retrieves interactions, prepares feature placeholders, aggregates
        repeat-pattern metadata, dynamically determines pending
        dependencies, and performs Qdrant-powered similarity search
        when vectors are available.

        Phase 2 additions:
        - Builds customer-level cluster summary with repeat metrics.
        - Builds deduplicated issue clusters via Union-Find.
        - Builds time-based clusters at daily, weekly, and monthly
          granularity.

        The ``clustering_ready`` flag remains ``False`` when upstream
        intelligence dependencies (summarisation, sentiment, etc.) are
        still missing.  However, ``clusters`` and ``repeat_issues`` are
        populated whenever Qdrant vectors are available — these are
        independent of the readiness check.

        No data is written back to PostgreSQL in this phase.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A :class:`CustomerClusteringResponse` with dynamically
            computed readiness information, similarity groups,
            repeat-issue metadata, customer clusters, issue clusters,
            and time-based clusters.
        """
        interactions = self.get_customer_interactions(customer_id)

        # Dynamically determine pending dependencies from actual data
        pending_dependencies: list[str] = []

        if any(
            interaction.query_summary is None
            for interaction in interactions
        ):
            pending_dependencies.append("query_summarization")

        if any(
            interaction.sentiment_label is None
            for interaction in interactions
        ):
            pending_dependencies.append("sentiment_analysis")

        if any(
            interaction.qdrant_vector_id is None
            for interaction in interactions
        ):
            pending_dependencies.append("embedding_generation")
            pending_dependencies.append("qdrant_configuration")

        clustering_ready = len(pending_dependencies) == 0

        # ── Vector availability counts ───────────────────────────────────
        vectors_available = sum(
            1 for i in interactions if i.qdrant_vector_id is not None
        )
        vectors_missing = len(interactions) - vectors_available

        # ── Qdrant similarity search and issue clustering (read-only) ────
        similarity_groups: list[SimilarityGroup] = []
        issue_clusters: list[IssueClusterGroup] = []
        repeat_issues: list[RepeatIssueDetail] = []
        persisted = False
        enriched_vectors: list[dict] = []

        if vectors_available > 0:
            try:
                from utils.scoring import convert_similarity_score
                enriched_vectors = self.fetch_customer_vectors(customer_id)
                similarity_groups = self.build_similarity_groups(customer_id, enriched_vectors=enriched_vectors)
                if similarity_groups:
                    issue_clusters = self.build_issue_clusters(
                        interactions=interactions,
                        similarity_groups=similarity_groups,
                    )
                    
                    # Derive repeat issues from issue clusters with interaction_count > 1
                    for cluster in issue_clusters:
                        if cluster.interaction_count > 1:
                            rep_id = cluster.interaction_ids[0]
                            rep_vid = None
                            for i in interactions:
                                if i.id == rep_id:
                                    rep_vid = i.qdrant_vector_id
                                    break
                            
                            avg_sim = cluster.similarity_score
                            detail = RepeatIssueDetail(
                                source_interaction_id=rep_id,
                                source_vector_id=rep_vid or "",
                                occurrence_count=cluster.interaction_count - 1,
                                similarity_scores=[avg_sim] * (cluster.interaction_count - 1) if avg_sim is not None else [],
                                similarity_score=avg_sim,
                            )
                            repeat_issues.append(detail)
            except Exception as exc:
                logger.error(
                    "Similarity search or issue clustering failed for customer_id=%s: %s",
                    customer_id,
                    exc,
                )
                # Gracefully degrade

        # ── Persist clusters to DB inside safe transaction ───────────────
        if vectors_available > 0 and issue_clusters:
            try:
                active_member_ids = []
                
                # Verify columns presence in live database schema
                from sqlalchemy import inspect
                inspector = inspect(self._db.bind)
                
                if inspector is not None:
                    ticket_cols = [c["name"] for c in inspector.get_columns("tickets")]
                    has_ticket_category = "category" in ticket_cols
                    
                    ai_cols = [c["name"] for c in inspector.get_columns("ai_analysis")]
                    has_ai_category = "category_prediction" in ai_cols
                else:
                    has_ticket_category = False
                    has_ai_category = False
                
                # Fetch category and ticket details for all interactions of this customer to avoid N+1 queries
                category_rows = (
                    self._db.query(
                        OperationalAnalysis.id,
                        tickets_table.c.category,
                        ai_analysis_table.c.category_prediction,
                        OperationalAnalysis.root_cause_category,
                        tickets_table.c.title,
                        tickets_table.c.description
                    )
                    .outerjoin(tickets_table, tickets_table.c.id == OperationalAnalysis.ticket_id)
                    .outerjoin(ai_analysis_table, ai_analysis_table.c.id == OperationalAnalysis.ai_analysis_id)
                    .filter(OperationalAnalysis.customer_id == customer_id)
                    .all()
                )
                
                interaction_meta = {}
                for row in category_rows:
                    interaction_meta[row[0]] = {
                        "ticket_category": row[1],
                        "ai_category": row[2],
                        "root_cause": row[3],
                        "title": row[4],
                        "description": row[5]
                    }

                # Query active clusters for customer (excluding the old mixed cluster '72a2a54b-e0ab-559a-9eec-2479273200c4')
                from sqlalchemy import text
                from models.issue_cluster import IssueCluster
                active_clusters = self._db.query(IssueCluster).filter(
                    self._db.query(OperationalAnalysis.id)
                    .filter(
                        OperationalAnalysis.cluster_id == IssueCluster.cluster_id,
                        OperationalAnalysis.customer_id == customer_id
                    )
                    .exists()
                ).filter(IssueCluster.cluster_id != uuid.UUID("72a2a54b-e0ab-559a-9eec-2479273200c4")).all()

                from collections import Counter

                for cluster in issue_clusters:
                    if cluster.interaction_count > 1:
                        # Find distinct member tickets and interactions
                        cluster_interactions = [i for i in interactions if i.id in cluster.interaction_ids]
                        ticket_ids_set = {i.ticket_id for i in cluster_interactions}
                        
                        # 1. Determine anchor ticket (earliest chronologically captured canonical main-ticket UUID)
                        valid_ints = [i for i in cluster_interactions if i.captured_at is not None]
                        if not valid_ints:
                            valid_ints = cluster_interactions
                        sorted_ints = sorted(valid_ints, key=lambda x: x.captured_at if x.captured_at is not None else datetime.min.replace(tzinfo=timezone.utc))
                        anchor_ticket_id = sorted_ints[0].ticket_id
                        
                        # Validation: Anchor ticket UUID must exist in the set of member ticket IDs
                        assert anchor_ticket_id in ticket_ids_set, f"Anchor ticket ID {anchor_ticket_id} must be in cluster member tickets {ticket_ids_set}"
                        
                        captured_dates = [i.captured_at for i in cluster_interactions if i.captured_at is not None]
                        first_seen = min(captured_dates, default=None)
                        last_seen = max(captured_dates, default=None)
                        
                        # Try to find a valid root cause category to satisfy foreign key validation
                        root_cause = None
                        for i in cluster_interactions:
                            if i.root_cause_category:
                                from models.issue_cluster import RootCauseTaxonomy
                                exists = self._db.query(RootCauseTaxonomy).filter_by(category=i.root_cause_category).first()
                                if exists:
                                    root_cause = i.root_cause_category
                                    break
                                    
                        # Dominant category resolution per distinct ticket_id:
                        ticket_resolved_categories = {}
                        for tid in ticket_ids_set:
                            ticket_ints = [i for i in cluster_interactions if i.ticket_id == tid]
                            raw_cat = None
                            
                            # 1. ai_analysis.category_prediction
                            if has_ai_category:
                                for i in ticket_ints:
                                    if i.ai_analysis_id:
                                        ai_row = self._db.execute(
                                            text("SELECT category_prediction FROM ai_analysis WHERE id = :aid"),
                                            {"aid": i.ai_analysis_id}
                                        ).mappings().first()
                                        if ai_row and ai_row["category_prediction"]:
                                            raw_cat = ai_row["category_prediction"]
                                            break
                                if raw_cat:
                                    ticket_resolved_categories[tid] = raw_cat
                                    continue
                                    
                            # 2. tickets.category
                            if has_ticket_category:
                                ticket_row = self._db.execute(
                                    text("SELECT category FROM tickets WHERE id = :tid"),
                                    {"tid": tid}
                                ).mappings().first()
                                if ticket_row and ticket_row["category"]:
                                    raw_cat = ticket_row["category"]
                                    ticket_resolved_categories[tid] = raw_cat
                                    continue
                                    
                            # 3. operational_analysis.root_cause_category
                            for i in ticket_ints:
                                if i.root_cause_category:
                                    raw_cat = i.root_cause_category
                                    break
                            if raw_cat:
                                ticket_resolved_categories[tid] = raw_cat
                                continue
                                
                            # 4. Keyword fallback
                            ticket_text_row = self._db.execute(
                                text("SELECT title, description FROM tickets WHERE id = :tid"),
                                {"tid": tid}
                            ).mappings().first()
                            title_text = ticket_text_row["title"] if ticket_text_row else ""
                            desc_text = ticket_text_row["description"] if ticket_text_row else ""
                            summary_text = ""
                            for i in ticket_ints:
                                if i.query_summary:
                                    summary_text = i.query_summary
                                    break
                                    
                            combined_text = f"{title_text or ''} {desc_text or ''} {summary_text or ''}".lower()
                            for kw, cat in {
                                "erp": "ERP",
                                "finance": "Finance",
                                "billing": "Finance",
                                "invoice": "Finance",
                                "tax": "Finance",
                                "auth": "Access Management",
                                "login": "Access Management",
                                "password": "Access Management",
                                "access": "Access Management",
                                "permission": "Access Management",
                                "report": "Reporting",
                                "db": "Database",
                                "database": "Database",
                                "network": "Network",
                                "wifi": "Network",
                                "wi-fi": "Network",
                                "performance": "Performance",
                                "slow": "Performance",
                                "outage": "Service Outage",
                                "down": "Service Outage",
                                "blue screen": "Software",
                                "bsod": "Software",
                            }.items():
                                if kw in combined_text:
                                    raw_cat = cat
                                    break
                            if raw_cat:
                                ticket_resolved_categories[tid] = raw_cat
                                continue
                                
                            # 5. General Support
                            ticket_resolved_categories[tid] = "General Support"
                            
                        # Get dominant resolved category
                        resolved_cats = list(ticket_resolved_categories.values())
                        dominant_raw_cat = Counter(resolved_cats).most_common(1)[0][0] if resolved_cats else "General Support"
                        
                        # Normalize display label
                        def _normalize_display_category(cat: str) -> str:
                            cat_clean = cat.strip().lower().replace("_", " ").replace("-", " ")
                            if cat_clean in ("access_management", "access management", "access_permission"):
                                return "Access Management"
                            if cat_clean in ("performance_degradation", "performance degradation"):
                                return "Performance"
                            if cat_clean in ("integration_failure", "integration failure"):
                                return "Integration Failure"
                            if cat_clean in ("software_bug", "software bug"):
                                return "Software"
                            if "auth" in cat_clean or "login" in cat_clean:
                                return "Authentication"
                            if "erp" in cat_clean:
                                return "ERP"
                            if "finance" in cat_clean or "billing" in cat_clean or "tax" in cat_clean or "invoice" in cat_clean:
                                return "Finance"
                            if "report" in cat_clean:
                                return "Reporting"
                            if "database" in cat_clean or "db" in cat_clean or "sql" in cat_clean:
                                return "Database"
                            if "network" in cat_clean or "wifi" in cat_clean or "wi-fi" in cat_clean:
                                return "Network"
                            if "performance" in cat_clean or "slow" in cat_clean:
                                return "Performance"
                            if "outage" in cat_clean or "down" in cat_clean:
                                return "Service Outage"
                            if "software" in cat_clean:
                                return "Software"
                            return cat.strip().title()
                            
                        display_cat = _normalize_display_category(dominant_raw_cat)
                        
                        # Generate concise cluster name based on keywords in ticket titles
                        subject_hits = Counter()
                        sorted_subjects = sorted(SUBJECT_MAPPING.keys(), key=len, reverse=True)
                        for tid in ticket_ids_set:
                            ticket_row = self._db.execute(
                                text("SELECT title FROM tickets WHERE id = :tid"),
                                {"tid": tid}
                            ).mappings().first()
                            title = (ticket_row["title"] if ticket_row else "").strip().lower()
                            if title:
                                for kw in sorted_subjects:
                                    if kw in title:
                                        subject_hits[SUBJECT_MAPPING[kw]] += 1
                                        break
                                        
                        if subject_hits:
                            cluster_name = subject_hits.most_common(1)[0][0]
                        else:
                            rc_list = [interaction_meta.get(mid, {}).get("root_cause") for mid in cluster.interaction_ids]
                            rc_candidates = [r for r in rc_list if r]
                            rc_dominant = Counter(rc_candidates).most_common(1)[0][0] if rc_candidates else "General"
                            rc_clean = rc_dominant.replace("_", " ").title()
                            if rc_clean.lower() in display_cat.lower():
                                cluster_name = f"{rc_clean} Access and Setup Issues" if "access" in rc_clean.lower() else f"{rc_clean} System Issues"
                            else:
                                cluster_name = f"{rc_clean} {display_cat} System Issues"
                                
                        # Map to broad category ensuring agreement with name keywords
                        def _map_to_broad_category(display_c: str, c_name: str) -> str:
                            name_lower = c_name.lower()
                            if "password" in name_lower or "reset" in name_lower:
                                return "Access Management"
                            if "login" in name_lower or "signin" in name_lower or "sign-in" in name_lower:
                                return "Authentication"
                            if "inventory" in name_lower or "wms" in name_lower:
                                return "ERP"
                            if "invoice" in name_lower or "tax" in name_lower:
                                return "Finance"
                            if "report" in name_lower or "reporting" in name_lower:
                                return "Reporting"
                            if "database" in name_lower or "sql" in name_lower or "query" in name_lower:
                                return "Database"
                            if "network" in name_lower or "connection" in name_lower or "wifi" in name_lower or "wi-fi" in name_lower:
                                return "Network"
                            if "performance" in name_lower or "slow" in name_lower or "degradation" in name_lower:
                                return "Performance"
                            if "outage" in name_lower or "downtime" in name_lower or "down" in name_lower:
                                return "Service Outage"
                            if "blue screen" in name_lower or "bsod" in name_lower:
                                return "Software"
                                
                            cat_lower = display_c.lower()
                            if "access" in cat_lower or "permission" in cat_lower:
                                return "Access Management"
                            if "auth" in cat_lower or "login" in cat_lower:
                                return "Authentication"
                            if "erp" in cat_lower or "integration" in cat_lower:
                                return "ERP"
                            if "finance" in cat_lower or "billing" in cat_lower or "tax" in cat_lower or "invoice" in cat_lower:
                                return "Finance"
                            if "report" in cat_lower:
                                return "Reporting"
                            if "database" in cat_lower or "db" in cat_lower:
                                return "Database"
                            if "network" in cat_lower or "wi-fi" in cat_lower or "wifi" in cat_lower:
                                return "Network"
                            if "performance" in cat_lower or "slow" in cat_lower:
                                return "Performance"
                            if "outage" in cat_lower or "down" in cat_lower:
                                return "Service Outage"
                            if "software" in cat_lower:
                                return "Software"
                            return "General Support"
                            
                        issue_cat = _map_to_broad_category(display_cat, cluster_name)
                        cluster.cluster_label = cluster_name
                        
                        # Active cluster reuse check
                        matched_existing = None
                        for existing in active_clusters:
                            if existing.issue_category != issue_cat:
                                continue
                            # Member overlap check:
                            if any(i.cluster_id == existing.cluster_id for i in cluster_interactions):
                                matched_existing = existing
                                break
                                
                        if matched_existing:
                            det_cluster_id = matched_existing.cluster_id
                        else:
                            stable_key = f"customer-{customer_id}-anchor-{str(anchor_ticket_id).lower().strip()}"
                            det_cluster_id = uuid.uuid5(uuid.NAMESPACE_DNS, stable_key)
                            
                        cluster.cluster_id = det_cluster_id
                        
                        # Calculate frequency from unique ticket IDs
                        frequency_count = len(ticket_ids_set)
                        
                        # 3. Upsert issue cluster record
                        self._repository.upsert_issue_cluster(
                            cluster_id=det_cluster_id,
                            cluster_name=cluster_name,
                            issue_category=issue_cat,
                            root_cause_category=root_cause,
                            frequency_count=frequency_count,
                            first_seen_at=first_seen,
                            last_seen_at=last_seen,
                        )
                        
                        # 4. Update interactions to link to this cluster
                        self._repository.bulk_update_interaction_cluster_ids(
                            interaction_ids=cluster.interaction_ids,
                            cluster_id=det_cluster_id,
                        )
                        
                        active_member_ids.extend(cluster.interaction_ids)
                        logger.info("Persisted issue cluster: name=%s id=%s count=%d frequency=%d", cluster.cluster_label, det_cluster_id, cluster.interaction_count, frequency_count)
                
                # 5. Safely clear other interactions for this customer not in active clusters
                self._repository.clear_interaction_cluster_ids(
                    customer_id=customer_id,
                    exclude_interaction_ids=active_member_ids,
                )
                
                # Commit changes
                logger.info("Saving OperationalAnalysis...")
                self._db.flush()
                logger.info("OperationalAnalysis saved successfully.")

                try:
                    from services.aggregation_service import AggregationService
                    aggregation_service = AggregationService(self._db)
                    aggregation_service.generate_all_rollups()
                    self._db.commit()
                    logger.info("Transaction committed successfully.")
                    persisted = True
                except Exception as exc:
                    self._db.rollback()
                    logger.error("Clustering rollup regeneration failed: %s", exc)
                    raise exc
                logger.info("Successfully committed issue cluster persistence for customer_id=%s", customer_id)
            except Exception as exc:
                self._db.rollback()
                logger.exception("Failed to persist clusters to database for customer_id=%s. Rolled back transaction.", customer_id)
                persisted = False

        # ── Phase 2: Repeat pattern metadata (with repeat metrics) ───────
        repeat_metadata = self.calculate_repeat_patterns(
            customer_id, repeat_issues=repeat_issues
        )

        # ── Phase 2: Customer-based clustering ───────────────────────────
        customer_cluster_summary = self.build_customer_cluster(
            customer_id=customer_id,
            interactions=interactions,
            repeat_issues=repeat_issues,
        )

        # ── Phase 2: Time-based clustering ───────────────────────────────
        time_clusters: list[TimeClusterResult] = []
        try:
            time_clusters = self.build_time_clusters(
                interactions=interactions,
                repeat_issues=repeat_issues,
            )
        except Exception as exc:
            logger.error(
                "Time clustering failed for customer_id=%s: %s",
                customer_id,
                exc,
            )

        # ── Repeat Issue Clustering (Parent/Subticket) ────────────────────
        repeat_issue_clusters = []
        try:
            repeat_issue_clusters = self.build_repeat_issue_clusters(
                customer_id=customer_id,
                interactions=interactions,
                enriched_vectors=enriched_vectors,
            )
        except Exception as exc:
            logger.error(
                "Repeat issue clustering failed for customer_id=%s: %s",
                customer_id,
                exc,
            )

        logger.info(
            "Clustering readiness for customer_id=%s: ready=%s "
            "pending=%s vectors=%d/%d groups=%d "
            "issue_clusters=%d time_clusters=%d repeat_issue_clusters=%d",
            customer_id,
            clustering_ready,
            pending_dependencies,
            vectors_available,
            len(interactions),
            len(similarity_groups),
            len(issue_clusters),
            len(time_clusters),
            len(repeat_issue_clusters),
        )

        return CustomerClusteringResponse(
            customer_id=customer_id,
            interaction_count=repeat_metadata.total_interactions,
            cluster_count=len(similarity_groups),
            clusters=similarity_groups,
            vectors_available=vectors_available,
            vectors_missing=vectors_missing,
            repeat_issues=repeat_issues,
            clustering_ready=clustering_ready,
            repeat_pattern_metadata=repeat_metadata,
            customer_clusters=customer_cluster_summary,
            issue_clusters=issue_clusters,
            time_clusters=time_clusters,
            persisted=persisted,
            repeat_issue_clusters=repeat_issue_clusters,
        )
