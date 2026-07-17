"""
schemas/intelligence.py
Pydantic data validation schemas for query summarizations, sentiment metrics, escalation risk scores, and root cause analysis responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

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
