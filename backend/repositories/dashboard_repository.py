"""
repositories/dashboard_repository.py
Abstractions and database query wrappers for compiling aggregated statistics from ticket rollups and customer health models.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from models.operational_analysis import OperationalAnalysis
from models.issue_cluster import IssueCluster
from models.customer_health import CustomerHealth
from models.ticket_rollup import TicketRollup


class DashboardRepository:
    """Access layer for dashboard analytics and aggregated database queries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Operational Dashboard Data Queries ────────────────────────────────

    def get_interaction_counts_and_averages(self) -> dict[str, Any]:
        """Fetch general stats and averages from operational_analysis table."""
        res = (
            self.db.query(
                func.count(OperationalAnalysis.id).label("total_interactions"),
                func.count(func.distinct(OperationalAnalysis.ticket_id)).label("total_tickets"),
                func.avg(OperationalAnalysis.sentiment_score).label("avg_sentiment"),
                func.avg(OperationalAnalysis.escalation_risk_score).label("avg_risk"),
            )
            .first()
        )

        resolved_count = (
            self.db.query(func.count(func.distinct(OperationalAnalysis.ticket_id)))
            .filter(
                OperationalAnalysis.response_summary.isnot(None),
                OperationalAnalysis.response_summary != "",
            )
            .scalar()
        ) or 0

        critical_count = (
            self.db.query(func.count(OperationalAnalysis.id))
            .filter(
                OperationalAnalysis.escalation_risk_band.in_(["critical", "high"])
            )
            .scalar()
        ) or 0

        return {
            "total_interactions": res.total_interactions or 0,
            "total_tickets": res.total_tickets or 0,
            "resolved_tickets": resolved_count,
            "average_sentiment": float(res.avg_sentiment) if res.avg_sentiment is not None else None,
            "average_escalation_risk": float(res.avg_risk) if res.avg_risk is not None else None,
            "critical_escalations_count": critical_count,
        }

    def get_recent_escalations(self, limit: int = 10) -> list[OperationalAnalysis]:
        """Retrieve recent high-risk or critical escalation records."""
        return (
            self.db.query(OperationalAnalysis)
            .filter(
                OperationalAnalysis.escalation_risk_band.in_(["critical", "high"])
            )
            .order_by(desc(OperationalAnalysis.captured_at))
            .limit(limit)
            .all()
        )

    def get_top_categories(self, limit: int = 5) -> list[tuple[str, int]]:
        """Retrieve the most frequent root cause categories."""
        rows = (
            self.db.query(
                OperationalAnalysis.root_cause_category,
                func.count(OperationalAnalysis.id).label("cnt"),
            )
            .filter(OperationalAnalysis.root_cause_category.isnot(None))
            .group_by(OperationalAnalysis.root_cause_category)
            .order_by(desc("cnt"))
            .limit(limit)
            .all()
        )
        return [(r[0], r[1]) for r in rows]

    def get_recent_clusters(self, limit: int = 5) -> list[IssueCluster]:
        """Retrieve recently modified issue clusters."""
        return (
            self.db.query(IssueCluster)
            .order_by(desc(IssueCluster.last_seen_at))
            .limit(limit)
            .all()
        )

    # ── Executive Dashboard Data Queries ──────────────────────────────────

    def get_overall_health_stats(self) -> dict[str, Any]:
        """Retrieve composite health stats from customer_health table."""
        avg_health = (
            self.db.query(func.avg(CustomerHealth.health_score)).scalar()
        ) or 100.0

        healthy = (
            self.db.query(func.count(CustomerHealth.id))
            .filter(CustomerHealth.health_score >= 80.0)
            .scalar()
        ) or 0

        warning = (
            self.db.query(func.count(CustomerHealth.id))
            .filter(
                CustomerHealth.health_score >= 50.0,
                CustomerHealth.health_score < 80.0,
            )
            .scalar()
        ) or 0

        critical = (
            self.db.query(func.count(CustomerHealth.id))
            .filter(CustomerHealth.health_score < 50.0)
            .scalar()
        ) or 0

        return {
            "overall_health_index": float(avg_health),
            "healthy_count": healthy,
            "warning_count": warning,
            "critical_count": critical,
        }

    def get_risk_distribution(self) -> dict[str, int]:
        """Count interactions in each escalation risk band."""
        rows = (
            self.db.query(
                OperationalAnalysis.escalation_risk_band,
                func.count(OperationalAnalysis.id),
            )
            .filter(OperationalAnalysis.escalation_risk_band.isnot(None))
            .group_by(OperationalAnalysis.escalation_risk_band)
            .all()
        )

        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for band, count in rows:
            norm_band = str(band).lower().strip()
            if norm_band in counts:
                counts[norm_band] = count

        return counts

    def get_weekly_trends(self, limit: int = 8) -> list[TicketRollup]:
        """Fetch weekly rollup records for trend analytics."""
        return (
            self.db.query(TicketRollup)
            .filter(TicketRollup.granularity == "weekly")
            .order_by(desc(TicketRollup.period_label))
            .limit(limit)
            .all()
        )[::-1]  # Return in chronological order (oldest to newest)

    def get_at_risk_customers(self, limit: int = 5) -> list[CustomerHealth]:
        """Fetch customer accounts sorted by lowest health score."""
        return (
            self.db.query(CustomerHealth)
            .order_by(CustomerHealth.health_score.asc())
            .limit(limit)
            .all()
        )

    # ── Customer Profile Specific Queries ────────────────────────────────

    def get_customer_interactions(self, customer_id: uuid.UUID) -> list[OperationalAnalysis]:
        """Fetch historical interactions for a specific customer."""
        return (
            self.db.query(OperationalAnalysis)
            .filter(OperationalAnalysis.customer_id == customer_id)
            .order_by(desc(OperationalAnalysis.captured_at))
            .all()
        )

    def get_customer_clusters(self, customer_id: uuid.UUID) -> list[IssueCluster]:
        """Fetch clusters associated with a customer's interactions."""
        # Query distinct non-null cluster_id from operational_analysis for this customer
        cluster_ids = (
            self.db.query(OperationalAnalysis.cluster_id)
            .filter(
                OperationalAnalysis.customer_id == customer_id,
                OperationalAnalysis.cluster_id.isnot(None),
            )
            .distinct()
            .all()
        )
        c_ids = [r[0] for r in cluster_ids]

        if not c_ids:
            return []

        return (
            self.db.query(IssueCluster)
            .filter(IssueCluster.cluster_id.in_(c_ids))
            .order_by(desc(IssueCluster.last_seen_at))
            .all()
        )
