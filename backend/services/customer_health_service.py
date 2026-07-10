"""
services/customer_health_service.py
Customer Health Service. Gathers aggregated customer interaction signals,
computes their composite health score, and updates the database.
"""

from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from repositories.cluster_repository import ClusterRepository
from repositories.customer_health_repository import CustomerHealthRepository
from intelligence.customer_health import CustomerHealthScorer

logger = setup_logger(__name__)


class CustomerHealthService:
    """Orchestrates customer health evaluation and updates."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._cluster_repo = ClusterRepository(db)
        self._health_repo = CustomerHealthRepository(db)

    def evaluate_customer_health(self, customer_id: uuid.UUID) -> Optional[float]:
        """Collect metrics, calculate health score, and persist for a customer.

        Args:
            customer_id: UUID of the customer to evaluate.

        Returns:
            The newly calculated health score (float), or None if no interactions exist.
        """
        logger.info("Evaluating customer health for customer_id=%s", customer_id)

        # 1. Check if customer has any interactions
        interaction_count = self._cluster_repo.get_customer_interaction_count(customer_id)
        if interaction_count == 0:
            logger.warning("No interactions found for customer_id=%s. Skipping health evaluation.", customer_id)
            return None

        # 2. Get average sentiment and escalation risk
        sentiment_average = self._cluster_repo.get_customer_sentiment_avg(customer_id)
        escalation_risk_average = self._cluster_repo.get_customer_escalation_risk_avg(customer_id)

        # 3. Get repeat issue metrics
        # We can construct repeat issue detail using the customer clustering service
        # or calculate it directly. Since customer clustering persists repeat patterns,
        # we can fetch the ratio of repeat interactions to total interactions.
        from services.customer_clustering_service import CustomerClusteringService
        clustering_service = CustomerClusteringService(self._db)
        clustering_response = clustering_service.group_customer_issues(customer_id)

        repeat_issue_frequency = 0.0
        if clustering_response.repeat_pattern_metadata:
            repeat_issue_frequency = clustering_response.repeat_pattern_metadata.repeated_issue_frequency

        # 4. Get resolution rate
        # Distinct tickets
        ticket_ids = self._cluster_repo.get_distinct_ticket_ids(customer_id)
        distinct_ticket_count = len(ticket_ids)

        resolution_rate = 1.0  # Default to 100% if no tickets exist
        if distinct_ticket_count > 0:
            # Count resolved tickets (where response_summary is present)
            resolved_ticket_count = (
                self._db.query(func.count(func.distinct(OperationalAnalysis.ticket_id)))
                .filter(
                    OperationalAnalysis.customer_id == customer_id,
                    OperationalAnalysis.response_summary.isnot(None),
                    OperationalAnalysis.response_summary != "",
                )
                .scalar()
            ) or 0

            resolution_rate = round(resolved_ticket_count / distinct_ticket_count, 4)
            logger.info(
                "Customer tickets: total=%d, resolved=%d, resolution_rate=%.4f",
                distinct_ticket_count,
                resolved_ticket_count,
                resolution_rate,
            )

        # 5. Calculate composite score
        health_score = CustomerHealthScorer.calculate_health_score(
            sentiment_average=sentiment_average,
            escalation_risk_average=escalation_risk_average,
            repeat_issue_frequency=repeat_issue_frequency,
            resolution_rate=resolution_rate,
        )

        # 6. Upsert and commit
        try:
            self._health_repo.upsert(
                customer_id=customer_id,
                health_score=health_score,
                sentiment_average=sentiment_average,
                escalation_risk_average=escalation_risk_average,
                repeat_issue_frequency=repeat_issue_frequency,
                resolution_rate=resolution_rate,
                interaction_count=interaction_count,
            )
            self._db.commit()
            logger.info(
                "Successfully persisted health score %.2f for customer_id=%s",
                health_score,
                customer_id,
            )
            return health_score
        except Exception as e:
            self._db.rollback()
            logger.error(
                "Failed to persist health score for customer_id=%s: %s",
                customer_id,
                e,
            )
            raise
