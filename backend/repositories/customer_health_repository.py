"""
repositories/customer_health_repository.py
Abstractions and database query wrappers for CRUD operations on CustomerHealth records.
"""

from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.orm import Session

from core.logging import setup_logger
from models.customer_health import CustomerHealth

logger = setup_logger(__name__)


class CustomerHealthRepository:
    """Data-access layer for CustomerHealth records.

    Provides pure database queries for retrieving and upserting health metrics.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_customer_id(self, customer_id: uuid.UUID) -> Optional[CustomerHealth]:
        """Fetch the health record for a specific customer.

        Args:
            customer_id: UUID of the customer.

        Returns:
            The matching CustomerHealth record or None if it does not exist.
        """
        return (
            self._db.query(CustomerHealth)
            .filter(CustomerHealth.customer_id == customer_id)
            .first()
        )

    def upsert(
        self,
        customer_id: uuid.UUID,
        health_score: float,
        sentiment_average: Optional[float] = None,
        escalation_risk_average: Optional[float] = None,
        repeat_issue_frequency: Optional[float] = None,
        resolution_rate: Optional[float] = None,
        interaction_count: int = 0,
    ) -> CustomerHealth:
        """Create or update a CustomerHealth record.

        Args:
            customer_id: UUID of the customer.
            health_score: Composite score.
            sentiment_average: Average sentiment.
            escalation_risk_average: Average escalation risk.
            repeat_issue_frequency: Ratio of repeat issues.
            resolution_rate: Ratio of resolved tickets.
            interaction_count: Total interactions.

        Returns:
            The upserted CustomerHealth record.
        """
        record = self.get_by_customer_id(customer_id)

        if record:
            logger.info("Updating existing customer health record for customer_id=%s", customer_id)
            record.health_score = health_score
            record.sentiment_average = sentiment_average
            record.escalation_risk_average = escalation_risk_average
            record.repeat_issue_frequency = repeat_issue_frequency
            record.resolution_rate = resolution_rate
            record.interaction_count = interaction_count
        else:
            logger.info("Creating new customer health record for customer_id=%s", customer_id)
            record = CustomerHealth(
                customer_id=customer_id,
                health_score=health_score,
                sentiment_average=sentiment_average,
                escalation_risk_average=escalation_risk_average,
                repeat_issue_frequency=repeat_issue_frequency,
                resolution_rate=resolution_rate,
                interaction_count=interaction_count,
            )
            self._db.add(record)

        self._db.flush()
        return record
