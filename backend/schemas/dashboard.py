"""
schemas/dashboard.py
Pydantic schemas formatting the responses for C-suite executive summaries and operational dashboards.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Operational Dashboard Schemas ─────────────────────────────────────────


class CategoryMetric(BaseModel):
    """Volume count per root-cause category."""

    category: str = Field(..., description="Root cause category label")
    count: int = Field(..., description="Number of interactions in this category")


class RecentEscalation(BaseModel):
    """Summary of a single high-risk escalation interaction."""

    interaction_id: uuid.UUID = Field(..., description="ID of the interaction record")
    ticket_id: uuid.UUID = Field(..., description="Source ticket identifier")
    ticket_key: Optional[str] = Field(
        default=None,
        description="Human-readable ticket reference"
    )
    customer_id: Optional[uuid.UUID] = Field(None, description="Customer identifier")
    customer_name: Optional[str] = Field(
        default=None,
        description="Human-readable customer name"
    )
    sentiment_label: Optional[str] = Field(None, description="Sentiment classification")
    escalation_risk_score: float = Field(..., description="Escalation risk probability")
    escalation_risk_band: str = Field(..., description="Risk band: high or critical")
    query_summary: Optional[str] = Field(None, description="Query summary statement")
    captured_at: datetime = Field(..., description="Timestamp event was captured")


class RecentCluster(BaseModel):
    """Summary of a recently generated issue cluster."""

    cluster_id: uuid.UUID = Field(..., description="Identifier of the cluster")
    cluster_name: Optional[str] = Field(None, description="System-generated label")
    issue_category: Optional[str] = Field(None, description="Category of the cluster")
    frequency_count: int = Field(..., description="Number of members in the cluster")
    last_seen_at: Optional[datetime] = Field(None, description="Timestamp of most recent member")


class OperationalDashboardResponse(BaseModel):
    """Data payload for the Operational/Support team dashboard."""

    total_interactions: int = Field(..., description="Total interaction records captured")
    total_tickets: int = Field(..., description="Total unique tickets captured")
    resolved_tickets: int = Field(..., description="Total resolved tickets (has response summary)")
    resolution_rate: float = Field(..., description="Ratio of resolved tickets")
    average_sentiment: Optional[float] = Field(None, description="Average sentiment score")
    average_escalation_risk: Optional[float] = Field(None, description="Average escalation risk score")
    critical_escalations_count: int = Field(..., description="Number of critical/high risk tickets")
    recent_escalations: list[RecentEscalation] = Field(
        default_factory=list, description="Recent high-risk escalations"
    )
    top_categories: list[CategoryMetric] = Field(
        default_factory=list, description="Most frequent root cause categories"
    )
    recent_clusters: list[RecentCluster] = Field(
        default_factory=list, description="Recently updated issue clusters"
    )


# ── Executive Dashboard Schemas ───────────────────────────────────────────


class HealthDistribution(BaseModel):
    """Count of accounts in distinct health buckets."""

    healthy_count: int = Field(..., description="Accounts with health_score >= 80")
    warning_count: int = Field(..., description="Accounts with health_score 50 to 79")
    critical_count: int = Field(..., description="Accounts with health_score < 50")


class RiskDistribution(BaseModel):
    """Count of interactions classified under each risk band."""

    critical_count: int = Field(..., description="Count of critical risk interactions")
    high_count: int = Field(..., description="Count of high risk interactions")
    medium_count: int = Field(..., description="Count of medium risk interactions")
    low_count: int = Field(..., description="Count of low risk interactions")


class TrendMetric(BaseModel):
    """Aggregated rollup indicators for a historical time period."""

    period_label: str = Field(..., description="Week or month identifier")
    interaction_count: int = Field(..., description="Total interactions during the period")
    ticket_count: int = Field(..., description="Total unique tickets during the period")
    resolution_rate: float = Field(..., description="Resolution rate during the period")
    average_sentiment: Optional[float] = Field(None, description="Average sentiment score")
    average_escalation_risk: Optional[float] = Field(None, description="Average escalation risk")


class AtRiskCustomer(BaseModel):
    """Summary of a customer account with low health or high escalation risk."""

    customer_id: uuid.UUID = Field(..., description="Identifier of the customer")
    customer_name: Optional[str] = Field(
        default=None,
        description="Human-readable customer name"
    )
    health_score: float = Field(..., description="Current customer health score (0-100)")
    sentiment_average: Optional[float] = Field(None, description="Average sentiment score")
    escalation_risk_average: Optional[float] = Field(None, description="Average escalation risk")
    interaction_count: int = Field(..., description="Total interactions for this customer")


class ExecutiveDashboardResponse(BaseModel):
    """Data payload for the C-suite Executive summary dashboard."""

    overall_health_index: float = Field(..., description="Average health score across all customer accounts")
    health_distribution: HealthDistribution = Field(..., description="Breakdown of customer account health states")
    average_sentiment: Optional[float] = Field(None, description="Mean sentiment score across all interactions")
    average_escalation_risk: Optional[float] = Field(None, description="Mean escalation risk across all interactions")
    risk_distribution: RiskDistribution = Field(..., description="Risk classification profile of interactions")
    weekly_trends: list[TrendMetric] = Field(
        default_factory=list, description="Weekly rolling analytics trends"
    )
    at_risk_customers: list[AtRiskCustomer] = Field(
        default_factory=list, description="Top customer accounts requiring attention"
    )


# ── Customer Dashboard Schemas ────────────────────────────────────────────


class CustomerInteractionDetail(BaseModel):
    """Individual interaction details for a customer profile view."""

    interaction_id: uuid.UUID = Field(..., description="Identifier of the record")
    ticket_id: uuid.UUID = Field(..., description="Source ticket identifier")
    query_summary: Optional[str] = Field(None, description="Customer problem summary")
    response_summary: Optional[str] = Field(None, description="Action taken resolution summary")
    sentiment_label: Optional[str] = Field(None, description="Sentiment classification")
    sentiment_score: Optional[float] = Field(None, description="Sentiment score")
    escalation_risk_score: Optional[float] = Field(None, description="Escalation risk score")
    escalation_risk_band: Optional[str] = Field(None, description="Escalation risk band")
    root_cause_category: Optional[str] = Field(None, description="Predicted root cause category")
    captured_at: datetime = Field(..., description="Timestamp event was captured")


class CustomerDashboardResponse(BaseModel):
    """Comprehensive health and interaction profile for a single customer."""

    customer_id: uuid.UUID = Field(..., description="The queried customer identifier")
    health_score: float = Field(..., description="Composite customer health score (0-100)")
    sentiment_average: Optional[float] = Field(None, description="Average sentiment score")
    escalation_risk_average: Optional[float] = Field(None, description="Average escalation risk score")
    repeat_issue_frequency: Optional[float] = Field(None, description="Ratio of repeat interactions")
    resolution_rate: Optional[float] = Field(None, description="Ratio of resolved tickets")
    interaction_count: int = Field(..., description="Total interaction records found")
    interactions: list[CustomerInteractionDetail] = Field(
        default_factory=list, description="Historical list of all interactions"
    )
    clusters: list[RecentCluster] = Field(
        default_factory=list, description="Topic/issue clusters associated with this customer"
    )
