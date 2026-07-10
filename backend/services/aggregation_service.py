"""
services/aggregation_service.py
Aggregation Service. Periodically calculates daily, weekly, and monthly
rollups of key metrics and updates the ticket_rollups table.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.logging import setup_logger
from models.operational_analysis import OperationalAnalysis
from models.ticket_rollup import TicketRollup
from utils.date_helpers import get_daily_key, get_weekly_key, get_monthly_key

logger = setup_logger(__name__)


class AggregationService:
    """Manages the generation and caching of daily, weekly, and monthly metrics rollups."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_all_rollups(self) -> int:
        """Run daily, weekly, and monthly aggregations across all interactions.

        Returns:
            The total number of rollup records updated or created.
        """
        logger.info("Starting aggregation run to rebuild ticket rollups")

        # 1. Retrieve all interaction records
        interactions = (
            self.db.query(OperationalAnalysis)
            .order_by(OperationalAnalysis.captured_at.asc())
            .all()
        )

        if not interactions:
            logger.info("No interaction records found. Rollup aggregation skipped.")
            return 0

        # Define granularities
        granularities = [
            ("daily", get_daily_key),
            ("weekly", get_weekly_key),
            ("monthly", get_monthly_key),
        ]

        total_upserted = 0

        for granularity, key_fn in granularities:
            # Group interactions by key
            groups: dict[str, list[OperationalAnalysis]] = defaultdict(list)
            for interaction in interactions:
                key = key_fn(interaction.captured_at)
                if key != "unknown":
                    groups[key].append(interaction)

            logger.info(
                "Aggregating granularity='%s': identified %d distinct periods",
                granularity,
                len(groups),
            )

            # Process each group
            for period_label, period_interactions in groups.items():
                interaction_count = len(period_interactions)

                # Collect unique tickets and resolved status
                tickets_all: set[str] = set()
                tickets_resolved: set[str] = set()

                sentiment_scores: list[float] = []
                risk_scores: list[float] = []
                critical_count = 0

                for i in period_interactions:
                    t_id_str = str(i.ticket_id)
                    tickets_all.add(t_id_str)

                    # Ticket is resolved if it has a populated response_summary
                    if i.response_summary and i.response_summary.strip():
                        tickets_resolved.add(t_id_str)

                    if i.sentiment_score is not None:
                        sentiment_scores.append(i.sentiment_score)

                    if i.escalation_risk_score is not None:
                        risk_scores.append(i.escalation_risk_score)

                    if i.escalation_risk_band and i.escalation_risk_band.lower() in (
                        "critical",
                        "high",
                    ):
                        critical_count += 1

                ticket_count = len(tickets_all)
                resolved_ticket_count = len(tickets_resolved)

                resolution_rate = 0.0
                if ticket_count > 0:
                    resolution_rate = round(resolved_ticket_count / ticket_count, 4)

                avg_sentiment = (
                    round(sum(sentiment_scores) / len(sentiment_scores), 4)
                    if sentiment_scores
                    else None
                )

                avg_risk = (
                    round(sum(risk_scores) / len(risk_scores), 4)
                    if risk_scores
                    else None
                )

                # Upsert Rollup Record
                rollup_record = (
                    self.db.query(TicketRollup)
                    .filter(
                        TicketRollup.period_label == period_label,
                        TicketRollup.granularity == granularity,
                    )
                    .first()
                )

                if rollup_record:
                    logger.debug(
                        "Updating existing rollup period_label=%s granularity=%s",
                        period_label,
                        granularity,
                    )
                    rollup_record.interaction_count = interaction_count
                    rollup_record.ticket_count = ticket_count
                    rollup_record.resolved_ticket_count = resolved_ticket_count
                    rollup_record.resolution_rate = resolution_rate
                    rollup_record.average_sentiment = avg_sentiment
                    rollup_record.average_escalation_risk = avg_risk
                    rollup_record.critical_escalation_count = critical_count
                    rollup_record.updated_at = datetime.now(timezone.utc)
                else:
                    logger.debug(
                        "Creating new rollup period_label=%s granularity=%s",
                        period_label,
                        granularity,
                    )
                    rollup_record = TicketRollup(
                        period_label=period_label,
                        granularity=granularity,
                        interaction_count=interaction_count,
                        ticket_count=ticket_count,
                        resolved_ticket_count=resolved_ticket_count,
                        resolution_rate=resolution_rate,
                        average_sentiment=avg_sentiment,
                        average_escalation_risk=avg_risk,
                        critical_escalation_count=critical_count,
                    )
                    self.db.add(rollup_record)

                total_upserted += 1

        try:
            self.db.commit()
            logger.info(
                "Aggregation run finished. Successfully upserted %d rollup records.",
                total_upserted,
            )
            return total_upserted
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to commit rollup aggregations to DB: %s", e)
            raise
