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

    Required fields: ``ticket_id``.
    """

    # Required identifiers
    ticket_id: uuid.UUID = Field(
        ..., description="Source ticket identifier"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ticket_id": "b9623e10-c4e2-411a-be33-d1f2bfa5113d",
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
