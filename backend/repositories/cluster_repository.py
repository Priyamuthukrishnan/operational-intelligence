"""
repositories/cluster_repository.py
Abstractions and database query wrappers for CRUD operations on issue clusters.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from models.issue_cluster import IssueCluster

logger = setup_logger(__name__)


class ClusterRepository:
    """Data-access layer for customer clustering queries.

    All methods are pure database operations — no business logic lives here.
    Queries target the :class:`OperationalAnalysis` model using dynamic
    filters on ``customer_id``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Read ─────────────────────────────────────────────────────────────

    def get_by_customer_id(
        self, customer_id: uuid.UUID
    ) -> list[OperationalAnalysis]:
        """Retrieve all interaction records for a given customer.

        Results are ordered by ``captured_at`` descending (most recent first).

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of matching :class:`OperationalAnalysis` records
            (may be empty).
        """
        records = (
            self._db.query(OperationalAnalysis)
            .filter(OperationalAnalysis.customer_id == customer_id)
            .order_by(OperationalAnalysis.captured_at.desc())
            .all()
        )
        logger.info(
            "Retrieved %d interaction(s) for customer_id=%s",
            len(records),
            customer_id,
        )
        return records

    def get_customer_interaction_count(
        self, customer_id: uuid.UUID
    ) -> int:
        """Return the total number of interactions for a customer.

        Args:
            customer_id: UUID of the customer.

        Returns:
            Integer count of matching records.
        """
        count = (
            self._db.query(func.count(OperationalAnalysis.id))
            .filter(OperationalAnalysis.customer_id == customer_id)
            .scalar()
        ) or 0
        logger.debug(
            "Interaction count for customer_id=%s: %d",
            customer_id,
            count,
        )
        return count

    def get_customer_issue_categories(
        self, customer_id: uuid.UUID
    ) -> list[str]:
        """Return distinct non-null root-cause categories for a customer.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of unique category strings (excludes ``None`` values).
        """
        rows = (
            self._db.query(OperationalAnalysis.root_cause_category)
            .filter(
                OperationalAnalysis.customer_id == customer_id,
                OperationalAnalysis.root_cause_category.isnot(None),
            )
            .distinct()
            .all()
        )
        categories = [row[0] for row in rows]
        logger.debug(
            "Distinct issue categories for customer_id=%s: %s",
            customer_id,
            categories,
        )
        return categories

    def get_interactions_with_vectors(
        self, customer_id: uuid.UUID
    ) -> list[OperationalAnalysis]:
        """Retrieve interactions that have a populated ``qdrant_vector_id``.

        Only returns records where the embedding has been generated and
        stored in Qdrant.  Used as the prerequisite filter before
        performing similarity searches.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of matching :class:`OperationalAnalysis` records
            that have a non-null ``qdrant_vector_id`` (may be empty).
        """
        records = (
            self._db.query(OperationalAnalysis)
            .filter(
                OperationalAnalysis.customer_id == customer_id,
                OperationalAnalysis.qdrant_vector_id.isnot(None),
            )
            .order_by(OperationalAnalysis.captured_at.desc())
            .all()
        )
        logger.info(
            "Retrieved %d interaction(s) with vectors for customer_id=%s",
            len(records),
            customer_id,
        )
        return records

    def get_distinct_ticket_ids(
        self, customer_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Return distinct ticket UUIDs for a customer.

        Args:
            customer_id: UUID of the customer.

        Returns:
            A list of unique ticket UUIDs.
        """
        rows = (
            self._db.query(OperationalAnalysis.ticket_id)
            .filter(OperationalAnalysis.customer_id == customer_id)
            .distinct()
            .all()
        )
        ticket_ids = [row[0] for row in rows]
        logger.debug(
            "Distinct ticket IDs for customer_id=%s: %d",
            customer_id,
            len(ticket_ids),
        )
        return ticket_ids

    def get_customer_sentiment_avg(
        self, customer_id: uuid.UUID
    ) -> Optional[float]:
        """Return the average sentiment score for a customer.

        Excludes ``None`` values from the calculation.

        Args:
            customer_id: UUID of the customer.

        Returns:
            The average sentiment score, or ``None`` if no scores exist.
        """
        result = (
            self._db.query(func.avg(OperationalAnalysis.sentiment_score))
            .filter(
                OperationalAnalysis.customer_id == customer_id,
                OperationalAnalysis.sentiment_score.isnot(None),
            )
            .scalar()
        )
        avg_val = float(result) if result is not None else None
        logger.debug(
            "Average sentiment score for customer_id=%s: %s",
            customer_id,
            avg_val,
        )
        return avg_val

    def get_customer_escalation_risk_avg(
        self, customer_id: uuid.UUID
    ) -> Optional[float]:
        """Return the average escalation risk score for a customer.

        Excludes ``None`` values from the calculation.

        Args:
            customer_id: UUID of the customer.

        Returns:
            The average escalation risk score, or ``None`` if no scores exist.
        """
        result = (
            self._db.query(
                func.avg(OperationalAnalysis.escalation_risk_score)
            )
            .filter(
                OperationalAnalysis.customer_id == customer_id,
                OperationalAnalysis.escalation_risk_score.isnot(None),
            )
            .scalar()
        )
        avg_val = float(result) if result is not None else None
        logger.debug(
            "Average escalation risk for customer_id=%s: %s",
            customer_id,
            avg_val,
        )
        return avg_val

    # ── Write / Persistence ──────────────────────────────────────────────

    def upsert_issue_cluster(
        self,
        cluster_id: uuid.UUID,
        cluster_name: str,
        issue_category: Optional[str],
        root_cause_category: Optional[str],
        frequency_count: int,
        first_seen_at: Optional[datetime],
        last_seen_at: Optional[datetime],
    ) -> IssueCluster:
        """Create or update a record in the issue_clusters table.

        Args:
            cluster_id: Deterministic UUID of the cluster.
            cluster_name: Temporary system-generated cluster label.
            issue_category: Category label for the cluster.
            root_cause_category: Root cause category for the cluster.
            frequency_count: Total similarity match occurrences.
            first_seen_at: Earliest captured_at timestamp of member interactions.
            last_seen_at: Latest captured_at timestamp of member interactions.

        Returns:
            The upserted IssueCluster record.
        """
        cluster = (
            self._db.query(IssueCluster)
            .filter(IssueCluster.cluster_id == cluster_id)
            .first()
        )

        if cluster:
            logger.info("Updating existing issue cluster: cluster_id=%s", cluster_id)
            cluster.cluster_name = cluster_name
            cluster.issue_category = issue_category
            cluster.root_cause_category = root_cause_category
            cluster.frequency_count = frequency_count
            cluster.first_seen_at = first_seen_at
            cluster.last_seen_at = last_seen_at
        else:
            logger.info("Creating new issue cluster record: cluster_id=%s", cluster_id)
            cluster = IssueCluster(
                cluster_id=cluster_id,
                cluster_name=cluster_name,
                issue_category=issue_category,
                root_cause_category=root_cause_category,
                frequency_count=frequency_count,
                first_seen_at=first_seen_at,
                last_seen_at=last_seen_at,
            )
            self._db.add(cluster)

        return cluster

    def update_interaction_cluster_id(
        self,
        interaction_id: uuid.UUID,
        cluster_id: Optional[uuid.UUID],
    ) -> None:
        """Update the cluster_id column for a single interaction.

        Args:
            interaction_id: UUID of the interaction record.
            cluster_id: UUID of the issue cluster, or None to clear.
        """
        self._db.query(OperationalAnalysis).filter(
            OperationalAnalysis.id == interaction_id
        ).update(
            {OperationalAnalysis.cluster_id: cluster_id},
            synchronize_session=False,
        )

    def bulk_update_interaction_cluster_ids(
        self,
        interaction_ids: list[uuid.UUID],
        cluster_id: Optional[uuid.UUID],
    ) -> None:
        """Bulk update the cluster_id column for a list of interactions.

        Args:
            interaction_ids: List of interaction record UUIDs.
            cluster_id: UUID of the issue cluster, or None to clear.
        """
        if not interaction_ids:
            return

        self._db.query(OperationalAnalysis).filter(
            OperationalAnalysis.id.in_(interaction_ids)
        ).update(
            {OperationalAnalysis.cluster_id: cluster_id},
            synchronize_session=False,
        )

    def clear_interaction_cluster_ids(
        self,
        customer_id: uuid.UUID,
        exclude_interaction_ids: list[uuid.UUID],
    ) -> None:
        """Safely clear the cluster_id column for this customer's interactions.

        Clears the cluster reference for interactions that are not part of
        the active issue clusters. Does not alter unrelated customer records.

        Args:
            customer_id: UUID of the customer.
            exclude_interaction_ids: Interactions that belong to active clusters.
        """
        query = self._db.query(OperationalAnalysis).filter(
            OperationalAnalysis.customer_id == customer_id
        )

        if exclude_interaction_ids:
            query = query.filter(
                OperationalAnalysis.id.not_in(exclude_interaction_ids)
            )

        updated_count = query.update(
            {OperationalAnalysis.cluster_id: None},
            synchronize_session=False,
        )
        logger.info(
            "Cleared cluster_id references for %d interaction(s) for customer_id=%s",
            updated_count,
            customer_id,
        )

    def get_cluster_by_id(
        self, cluster_id: uuid.UUID
    ) -> Optional[IssueCluster]:
        """Retrieve a persisted cluster record by its ID.

        Args:
            cluster_id: UUID of the cluster.

        Returns:
            The IssueCluster record, or None if not found.
        """
        return (
            self._db.query(IssueCluster)
            .filter(IssueCluster.cluster_id == cluster_id)
            .first()
        )

    def get_cluster_members(
        self, cluster_id: uuid.UUID
    ) -> list[OperationalAnalysis]:
        """Retrieve all interaction records associated with a cluster.

        Args:
            cluster_id: UUID of the cluster.

        Returns:
            A list of matching OperationalAnalysis records.
        """
        return (
            self._db.query(OperationalAnalysis)
            .filter(OperationalAnalysis.cluster_id == cluster_id)
            .all()
        )


