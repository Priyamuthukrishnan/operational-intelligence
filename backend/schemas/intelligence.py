"""
schemas/intelligence.py
Pydantic data validation schemas for query summarizations, sentiment metrics, escalation risk scores, and root cause analysis responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

class OverallRiskInfo(BaseModel):
    score: int = Field(..., description="Overall risk score (0-100)")
    band: str = Field(..., description="Risk classification band (LOW, MEDIUM, HIGH, CRITICAL)")

class IncidentHistoryInfo(BaseModel):
    repeated_issue: bool = Field(..., description="Flag indicating repeated customer issue")
    occurrences: int = Field(..., description="Number of occurrences")
    sub_tickets: int = Field(..., description="Number of linked sub-tickets")

class CustomerSentimentInfo(BaseModel):
    label: str = Field(..., description="Customer sentiment label")

class ManagerEscalationInfo(BaseModel):
    status: str = Field(..., description="Manager escalation status (Escalated, Pending Review, Not Required)")

class OperationalInsightInfo(BaseModel):
    title: str = Field(..., description="Insight title in business language")
    summary: str = Field(..., description="Business-facing summary")
    top_factors: list[str] = Field(default_factory=list, description="Top contributing factors")

class BusinessViewInfo(BaseModel):
    overall_risk: OverallRiskInfo
    incident_history: IncidentHistoryInfo
    customer_sentiment: CustomerSentimentInfo
    manager_escalation: ManagerEscalationInfo
    operational_insight: OperationalInsightInfo
    recommendation: str
    primary_recommendation: Optional[str] = Field(None, description="Single primary recommended action for manager")
    supporting_observations: list[str] = Field(default_factory=list, description="Supporting context observations")
    lifecycle_stage: Optional[str] = Field(None, description="Human-readable lifecycle position (First Occurrence, Repeat Issue, Manager Escalation)")
    priority: Optional[str] = Field(None, description="Ticket priority level")
    ticket_age_hours: Optional[float] = Field(None, description="Hours since earliest recorded activity")
    activity_summary: Optional[str] = Field(None, description="Brief summary of operational activity counts")

class TicketRiskResponse(BaseModel):
    """Escalation risk analysis report for a single ticket."""
    ticket_id: uuid.UUID = Field(..., description="Source ticket identifier")
    analysis_id: uuid.UUID = Field(..., description="Primary key of the analysis interaction record")
    sentiment_label: Optional[str] = Field(None, description="Sentiment classification label (positive, neutral, negative)")
    sentiment_score: Optional[float] = Field(None, description="Sentiment score converted to a 0-10 display scale")
    risk_score: Optional[float] = Field(None, description="Escalation risk score converted to a 0-10 display scale")
    risk_band: Optional[str] = Field(None, description="Risk classification band (LOW, MEDIUM, HIGH, CRITICAL)")
    confidence_score: Optional[float] = Field(None, description="Confidence decay score scaled to 0-10 display range")
    momentum_score: Optional[float] = Field(None, description="Interaction velocity/momentum factor")
    risk_multiplier: Optional[float] = Field(None, description="Calculated multiplier applied to baseline risk")
    risk_reason: Optional[dict[str, Any]] = Field(None, description="Detailed signal breakdown explaining how the risk score was calculated")
    risk_processed: bool = Field(..., description="Flag indicating whether risk processing has finished")
    captured_at: datetime = Field(..., description="Timestamp of calculation snapshot")
    business: Optional[BusinessViewInfo] = Field(None, description="Clean business view object for managers and business users")

