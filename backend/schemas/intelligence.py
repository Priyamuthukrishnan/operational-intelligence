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
    escalation_risk_score: float = Field(..., description="Escalation risk probability (0.0 to 1.0)")
    escalation_risk_score_out_of_10: Optional[float] = Field(None, description="Escalation risk score scaled out of 10")
    escalation_risk_band: str = Field(..., description="Risk classification band")
    confidence_decay_score: float = Field(..., description="Raw confidence decay score (0.0 to 20.0)")
    confidence_decay_score_out_of_10: Optional[float] = Field(None, description="Confidence decay score scaled out of 10")
    momentum_score: float = Field(..., description="Interaction velocity/momentum factor")
    risk_multiplier: float = Field(..., description="Calculated multiplier applied to baseline risk")
    risk_reason: Optional[dict[str, Any]] = Field(None, description="Detailed signals and multiplier explanation")
    risk_processed: bool = Field(..., description="Flag indicating whether risk processing has finished")
    captured_at: datetime = Field(..., description="Timestamp of calculation snapshot")
