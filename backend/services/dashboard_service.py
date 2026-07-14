"""
services/dashboard_service.py
Dashboard Aggregator Service. Fetches, caches, and shapes metric records
to supply clean structures to dashboard router endpoints.
"""

from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from core.logging import setup_logger
from repositories.dashboard_repository import DashboardRepository
from repositories.customer_health_repository import CustomerHealthRepository

logger = setup_logger(__name__)
from utils.scoring import (
    convert_sentiment_score,
    convert_escalation_risk_score,
    convert_health_score,
    convert_root_cause_confidence,
)
from schemas.dashboard import (
    OperationalDashboardResponse,
    RecentEscalation,
    CategoryMetric,
    RecentCluster,
    ExecutiveDashboardResponse,
    HealthDistribution,
    RiskDistribution,
    TrendMetric,
    AtRiskCustomer,
    CustomerDashboardResponse,
    CustomerInteractionDetail,
)


class DashboardService:
    """Consolidates database queries from DashboardRepository and formats
    them into validated Pydantic models.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = DashboardRepository(db)
        self.health_repo = CustomerHealthRepository(db)

    def get_operational_dashboard(self) -> OperationalDashboardResponse:
        """Fetch and format operational/support dashboard details."""
        stats = self.repo.get_interaction_counts_and_averages()
        escalations = self.repo.get_recent_escalations(limit=10)
        categories = self.repo.get_top_categories(limit=5)
        clusters = self.repo.get_recent_clusters(limit=5)

        resolution_rate = 0.0
        if stats["total_tickets"] > 0:
            resolution_rate = round(stats["resolved_tickets"] / stats["total_tickets"], 4)

        recent_escalations = [
            RecentEscalation(
                interaction_id=e.id,
                ticket_id=e.ticket_id,
                ticket_key=ticket_key,
                customer_id=e.customer_id,
                customer_name=customer_name,
                sentiment_label=e.sentiment_label,
                escalation_risk_score=e.escalation_risk_score or 0.0,
                escalation_risk_score_out_of_10=convert_escalation_risk_score(e.escalation_risk_score),
                escalation_risk_band=e.escalation_risk_band or "high",
                query_summary=e.query_summary,
                repeat_count=e.repeat_count,
                resolution_state=e.resolution_state,
                captured_at=e.captured_at,
            )
            for e, ticket_key, customer_name in escalations
        ]

        top_categories = [
            CategoryMetric(category=cat, count=cnt) for cat, cnt in categories
        ]

        from models.operational_analysis import OperationalAnalysis
        from repositories.dashboard_repository import users_table

        recent_clusters = []
        for c in clusters:
            customer_id = None
            customer_name = None
            member = (
                self.db.query(
                    OperationalAnalysis.customer_id,
                    users_table.c.name
                )
                .outerjoin(users_table, users_table.c.id == OperationalAnalysis.customer_id)
                .filter(OperationalAnalysis.cluster_id == c.cluster_id)
                .first()
            )
            if member:
                customer_id = member[0]
                customer_name = member[1]

            recent_clusters.append(
                RecentCluster(
                    cluster_id=c.cluster_id,
                    customer_id=customer_id,
                    customer_name=customer_name,
                    cluster_name=c.cluster_name,
                    issue_category=c.issue_category,
                    frequency_count=c.frequency_count or 0,
                    last_seen_at=c.last_seen_at,
                )
            )

        return OperationalDashboardResponse(
            total_interactions=stats["total_interactions"],
            total_tickets=stats["total_tickets"],
            resolved_tickets=stats["resolved_tickets"],
            resolution_rate=resolution_rate,
            average_sentiment=stats["average_sentiment"],
            average_sentiment_out_of_10=convert_sentiment_score(stats["average_sentiment"]),
            average_escalation_risk=stats["average_escalation_risk"],
            average_escalation_risk_out_of_10=convert_escalation_risk_score(stats["average_escalation_risk"]),
            critical_escalations_count=stats["critical_escalations_count"],
            recent_escalations=recent_escalations,
            top_categories=top_categories,
            recent_clusters=recent_clusters,
        )

    def get_executive_dashboard(self) -> ExecutiveDashboardResponse:
        """Fetch and format C-suite summary dashboard details."""
        health_stats = self.repo.get_overall_health_stats()
        risk_counts = self.repo.get_risk_distribution()
        trends = self.repo.get_weekly_trends(limit=8)
        at_risk_list = self.repo.get_at_risk_customers(limit=5)

        # Totals and global averages
        general_stats = self.repo.get_interaction_counts_and_averages()

        health_dist = HealthDistribution(
            healthy_count=health_stats["healthy_count"],
            warning_count=health_stats["warning_count"],
            critical_count=health_stats["critical_count"],
        )

        risk_dist = RiskDistribution(
            critical_count=risk_counts["critical"],
            high_count=risk_counts["high"],
            medium_count=risk_counts["medium"],
            low_count=risk_counts["low"],
        )

        weekly_trends = [
            TrendMetric(
                period_label=t.period_label,
                interaction_count=t.interaction_count,
                ticket_count=t.ticket_count,
                resolution_rate=t.resolution_rate,
                average_sentiment=t.average_sentiment,
                average_sentiment_out_of_10=convert_sentiment_score(t.average_sentiment),
                average_escalation_risk=t.average_escalation_risk,
                average_escalation_risk_out_of_10=convert_escalation_risk_score(t.average_escalation_risk),
            )
            for t in trends
        ]

        at_risk_customers = []
        for c, customer_name in at_risk_list:
            if customer_name is None:
                logger.warning(
                    "Missing user relationship for customer_id=%s in customer_health",
                    c.customer_id,
                )
            at_risk_customers.append(
                AtRiskCustomer(
                    customer_id=c.customer_id,
                    customer_name=customer_name,
                    health_score=c.health_score,
                    health_score_out_of_10=convert_health_score(c.health_score),
                    sentiment_average=c.sentiment_average,
                    sentiment_average_out_of_10=convert_sentiment_score(c.sentiment_average),
                    escalation_risk_average=c.escalation_risk_average,
                    escalation_risk_average_out_of_10=convert_escalation_risk_score(c.escalation_risk_average),
                    interaction_count=c.interaction_count,
                )
            )

        return ExecutiveDashboardResponse(
            overall_health_index=health_stats["overall_health_index"],
            overall_health_index_out_of_10=convert_health_score(health_stats["overall_health_index"]),
            health_distribution=health_dist,
            average_sentiment=general_stats["average_sentiment"],
            average_sentiment_out_of_10=convert_sentiment_score(general_stats["average_sentiment"]),
            average_escalation_risk=general_stats["average_escalation_risk"],
            average_escalation_risk_out_of_10=convert_escalation_risk_score(general_stats["average_escalation_risk"]),
            risk_distribution=risk_dist,
            weekly_trends=weekly_trends,
            at_risk_customers=at_risk_customers,
        )

    def get_customer_dashboard(self, customer_id: uuid.UUID) -> CustomerDashboardResponse:
        """Fetch and format detailed metrics profile for a single customer."""
        health_record = self.health_repo.get_by_customer_id(customer_id)
        interactions = self.repo.get_customer_interactions(customer_id)
        clusters = self.repo.get_customer_clusters(customer_id)

        # Fallback values if health evaluation has not run yet
        health_score = 100.0
        sentiment_avg = None
        risk_avg = None
        repeat_freq = None
        res_rate = None

        if health_record:
            health_score = health_record.health_score
            sentiment_avg = health_record.sentiment_average
            risk_avg = health_record.escalation_risk_average
            repeat_freq = health_record.repeat_issue_frequency
            res_rate = health_record.resolution_rate

        detail_list = [
            CustomerInteractionDetail(
                interaction_id=i.id,
                ticket_id=i.ticket_id,
                query_summary=i.query_summary,
                response_summary=i.response_summary,
                sentiment_label=i.sentiment_label,
                sentiment_score=i.sentiment_score,
                sentiment_score_out_of_10=convert_sentiment_score(i.sentiment_score),
                escalation_risk_score=i.escalation_risk_score,
                escalation_risk_score_out_of_10=convert_escalation_risk_score(i.escalation_risk_score),
                escalation_risk_band=i.escalation_risk_band,
                root_cause_confidence_out_of_10=convert_root_cause_confidence(i.root_cause_confidence),
                root_cause_category=i.root_cause_category,
                captured_at=i.captured_at,
            )
            for i in interactions
        ]

        associated_clusters = [
            RecentCluster(
                cluster_id=c.cluster_id,
                cluster_name=c.cluster_name,
                issue_category=c.issue_category,
                frequency_count=c.frequency_count or 0,
                last_seen_at=c.last_seen_at,
            )
            for c in clusters
        ]

        return CustomerDashboardResponse(
            customer_id=customer_id,
            health_score=health_score,
            health_score_out_of_10=convert_health_score(health_score),
            sentiment_average=sentiment_avg,
            sentiment_average_out_of_10=convert_sentiment_score(sentiment_avg),
            escalation_risk_average=risk_avg,
            escalation_risk_average_out_of_10=convert_escalation_risk_score(risk_avg),
            repeat_issue_frequency=repeat_freq,
            resolution_rate=res_rate,
            interaction_count=len(interactions),
            interactions=detail_list,
            clusters=associated_clusters,
        )
