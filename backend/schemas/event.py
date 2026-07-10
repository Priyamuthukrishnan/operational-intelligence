"""
schemas/event.py
Pydantic data serialization schemas for incoming interaction events.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.constants import (
    ESCALATION_RISK_SCORE_MAX,
    ESCALATION_RISK_SCORE_MIN,
    REPEAT_COUNT_MIN,
    SENTIMENT_SCORE_MAX,
    SENTIMENT_SCORE_MIN,
)


# ── Request Schema ───────────────────────────────────────────────────────


class EventCaptureRequest(BaseModel):
    """Inbound payload from the Service Intelligence layer.

    Required fields: ``ai_analysis_id``, ``ticket_id``, ``customer_id``.
    All enrichment fields are optional — they are populated later by
    downstream intelligence modules.
    """

    # Required identifiers
    ai_analysis_id: uuid.UUID = Field(
        ..., description="Analysis ID from the Service Intelligence layer"
    )
    ticket_id: uuid.UUID = Field(
        ..., description="Source ticket identifier"
    )
    customer_id: uuid.UUID = Field(
        ..., description="Customer identifier"
    )

    # Optional identifiers
    comment_id: Optional[uuid.UUID] = Field(
        None, description="Specific comment within the ticket"
    )

    # Risk escalation snapshot fields
    source_used: Optional[str] = Field(
        None,
        description="How the issue was handled at this snapshot (rag, runbook, hybrid, human, manager)",
    )
    assigned_agent_id: Optional[uuid.UUID] = Field(
        None, description="Assigned agent identifier at this snapshot"
    )
    assigned_manager_id: Optional[uuid.UUID] = Field(
        None, description="Assigned manager identifier at this snapshot"
    )
    resolution_state: Optional[str] = Field(
        None,
        description="Resolution state snapshot (open, waiting, resolved, closed)",
    )

    # Summarisation (optional enrichment)
    query_summary: Optional[str] = Field(
        None, description="AI-generated summary of the customer query"
    )
    response_summary: Optional[str] = Field(
        None, description="AI-generated summary of the agent response"
    )

    # Sentiment (optional enrichment)
    sentiment_label: Optional[str] = Field(
        None, description="Sentiment classification label"
    )
    sentiment_score: Optional[float] = Field(
        None, description="Sentiment score in range [-1.0, 1.0]"
    )

    # Escalation risk (optional enrichment)
    escalation_risk_score: Optional[float] = Field(
        None, description="Escalation risk probability in range [0.0, 1.0]"
    )
    escalation_risk_band: Optional[str] = Field(
        None, description="Escalation risk classification band"
    )

    # Root cause (optional enrichment)
    root_cause_category: Optional[str] = Field(
        None, description="Predicted root-cause category"
    )
    root_cause_confidence: Optional[float] = Field(
        None, description="Confidence of root-cause prediction"
    )

    # Clustering / embeddings (optional enrichment)
    repeat_count: Optional[int] = Field(
        None, description="Number of times issue has been repeated"
    )
    cluster_id: Optional[uuid.UUID] = Field(
        None, description="Assigned cluster identifier"
    )
    qdrant_vector_id: Optional[str] = Field(
        None, description="Vector ID in Qdrant store"
    )

    # Metadata
    model_version: Optional[str] = Field(
        None, description="AI model version used for analysis"
    )

    # ── Validators ───────────────────────────────────────────────────────

    @field_validator("sentiment_score")
    @classmethod
    def validate_sentiment_score(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not (SENTIMENT_SCORE_MIN <= value <= SENTIMENT_SCORE_MAX):
            raise ValueError(
                f"sentiment_score must be between {SENTIMENT_SCORE_MIN} and "
                f"{SENTIMENT_SCORE_MAX}, got {value}"
            )
        return value

    @field_validator("escalation_risk_score")
    @classmethod
    def validate_escalation_risk_score(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not (
            ESCALATION_RISK_SCORE_MIN <= value <= ESCALATION_RISK_SCORE_MAX
        ):
            raise ValueError(
                f"escalation_risk_score must be between "
                f"{ESCALATION_RISK_SCORE_MIN} and {ESCALATION_RISK_SCORE_MAX}, "
                f"got {value}"
            )
        return value

    @field_validator("repeat_count")
    @classmethod
    def validate_repeat_count(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < REPEAT_COUNT_MIN:
            raise ValueError(
                f"repeat_count cannot be negative, got {value}"
            )
        return value

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ai_analysis_id": "4b92b678-43df-4033-91a5-81679093bf7b",
                    "ticket_id": "b9623e10-c4e2-411a-be33-d1f2bfa5113d",
                    "customer_id": "3c983a56-ee25-4c07-ba71-a083d03cb1df",
                    "comment_id": "f5b828cd-bb88-410a-8bf8-d1d8df5c2692",
                    "sentiment_label": "negative",
                    "sentiment_score": -0.72,
                    "escalation_risk_score": 0.85,
                    "escalation_risk_band": "high",
                    "model_version": "v2.1.0",
                }
            ]
        }
    }


# ── Response Schema ──────────────────────────────────────────────────────


class EventCaptureResponse(BaseModel):
    """Standard response returned after an event has been captured."""

    status: str = Field(
        "success", description="Outcome status of the capture operation"
    )
    message: str = Field(
        "Event captured successfully",
        description="Human-readable result message",
    )
    operational_analysis_id: str = Field(
        ..., description="Generated UUID of the persisted analytics record"
    )
