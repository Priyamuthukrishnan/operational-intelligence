"""Deterministic escalation risk scoring utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.operational_analysis import OperationalAnalysis


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _hours_between(later, earlier):
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=timezone.utc)

    if later.tzinfo is None:
        later = later.replace(tzinfo=timezone.utc)

    return max((later - earlier).total_seconds() / 3600.0, 0.0)


def _latest_non_null(history: list[OperationalAnalysis], attr: str) -> Any:
    for row in reversed(history):
        value = getattr(row, attr, None)
        if value is not None:
            return value
    return None


def compute_escalation_level(
    latest: OperationalAnalysis,
    ai_source_used: str | None = None,
    recommendation_source: str | None = None,
    approval_action: str | None = None,
) -> int:
    latest_source = _norm(ai_source_used)
    recommendation_source = _norm(recommendation_source)
    approval_action = _norm(approval_action)

    if approval_action in {"escalated", "escalation_requested", "approved"}:
        return 35
    if recommendation_source in {"escalation", "manager", "supervisor", "urgent"}:
        return 30
    if latest_source in {"manager", "human"}:
        return 28
    if latest_source == "hybrid":
        return 18
    if latest_source == "runbook":
        return 10
    return 0


def compute_confidence_decay(
    history: list[OperationalAnalysis],
    ai_confidences: list[float] | None = None,
    latest_recommendation_source: str | None = None,
    latest_approval_action: str | None = None,
) -> float:
    root_confidences = [
        float(row.root_cause_confidence)
        for row in history
        if row.root_cause_confidence is not None
    ]
    ai_confidences = [
        float(value)
        for value in (ai_confidences or [])
        if value is not None
    ]

    source_history = root_confidences if len(root_confidences) >= 2 else ai_confidences
    if len(source_history) < 2:
        return 0.0

    oldest = source_history[0]
    latest = source_history[-1]
    delta = latest - oldest
    decay = max(0.0, -delta * 40.0)

    recommendation_source = _norm(latest_recommendation_source)
    approval_action = _norm(latest_approval_action)
    if recommendation_source in {"uncertain", "hold", "review", "human"}:
        decay += 2.0
    if approval_action in {"denied", "rejected", "escalation_requested"}:
        decay += 3.0

    return round(min(decay, 20.0), 2)


def compute_semantic_repetition(history: list[OperationalAnalysis]) -> int:
    repeat_count = _latest_non_null(history, "repeat_count")
    if repeat_count is None:
        repeat_count = 0

    repeat_count = int(repeat_count)
    if repeat_count <= 0:
        return 0
    if repeat_count == 1:
        return 6
    if repeat_count <= 3:
        return 12
    return 20


def compute_sentiment_trend(history: list[OperationalAnalysis]) -> int:
    sentiment = _latest_non_null(history, "sentiment_score")
    if sentiment is None:
        return 0

    sentiment = float(sentiment)
    if sentiment >= 0:
        return 0
    if sentiment >= -0.20:
        return 4
    if sentiment >= -0.40:
        return 9
    return 15


def compute_ticket_momentum(
    ticket_status: str | None = None,
    latest_activity_at: datetime | None = None,
) -> int:
    latest_status = _norm(ticket_status)
    if latest_status in {"resolved", "closed", "cancelled"}:
        return 0

    if latest_activity_at is None:
        return 0

    age_hours = _hours_between(datetime.now(timezone.utc), latest_activity_at)
    if age_hours is None:
        return 0
    if age_hours < 12.0:
        return 0
    if age_hours < 24.0:
        return 5
    if age_hours < 48.0:
        return 12
    return 18


def apply_multiplier(
    history: list[OperationalAnalysis],
    signal_scores: dict[str, int | float],
    escalation_source: str | None = None,
) -> tuple[float, str]:
    if not history:
        return 1.0, "none"

    source_used = _norm(escalation_source)
    escalation_level = int(signal_scores.get("escalation_level", 0))
    confidence_decay = float(signal_scores.get("confidence_decay", 0.0))
    repetition = int(signal_scores.get("semantic_repetition", 0))
    sentiment = int(signal_scores.get("sentiment_trend", 0))
    momentum = int(signal_scores.get("ticket_momentum", 0))

    candidates: list[tuple[float, str, bool]] = [
        (
            1.35,
            "human escalation with no progress >48h",
            escalation_level >= 28
            and source_used in {"human", "manager"}
            and confidence_decay >= 8.0,
        ),
        (
            1.30,
            "negative sentiment with human stagnation",
            sentiment > 0
            and source_used in {"human", "manager"}
            and momentum >= 12,
        ),
        (
            1.25,
            "low confidence with high repetition",
            confidence_decay >= 8.0 and repetition >= 12,
        ),
    ]

    for multiplier, reason, applies in candidates:
        if applies:
            return multiplier, reason

    return 1.0, "none"


def normalize_score(score: float) -> int:
    return max(0, min(100, int(round(score))))


def map_risk_band(score: int) -> str:
    if score <= 24:
        return "LOW"
    if score <= 49:
        return "MEDIUM"
    if score <= 74:
        return "HIGH"
    return "CRITICAL"


def build_risk_reason(
    signal_scores: dict[str, int | float],
    multiplier: float,
    multiplier_reason: str,
) -> dict:
    signals = {
        "escalation": int(signal_scores.get("escalation_level", 0)),
        "confidence": float(signal_scores.get("confidence_decay", 0.0)),
        "repetition": int(signal_scores.get("semantic_repetition", 0)),
        "sentiment": int(signal_scores.get("sentiment_trend", 0)),
        "momentum": int(signal_scores.get("ticket_momentum", 0)),
    }

    raw_score = sum(float(v) for v in signal_scores.values())

    reason: dict = {
        "signals": signals,
        "raw_score": raw_score,
        "multiplier": float(multiplier),
    }
    if multiplier_reason and multiplier_reason != "none":
        reason["multiplier_reason"] = multiplier_reason

    return reason


def compute(
    history: list[OperationalAnalysis],
    escalation_source: str | None = None,
    recommendation_source: str | None = None,
    approval_action: str | None = None,
    ai_confidences: list[float] | None = None,
    ticket_status: str | None = None,
    latest_activity_at: datetime | None = None,
) -> dict[str, Any]:
    if not history:
        signal_scores = {
            "escalation_level": 0,
            "confidence_decay": 0.0,
            "semantic_repetition": 0,
            "sentiment_trend": 0,
            "ticket_momentum": 0,
        }
        risk_reason = build_risk_reason(signal_scores, 1.0, "none")
        return {
            "raw_score": 0,
            "final_score": 0,
            "escalation_risk_score": 0.0,
            "escalation_risk_band": "LOW",
            "confidence_decay_score": 0.0,
            "momentum_score": 0.0,
            "risk_multiplier": 1.0,
            "risk_reason": risk_reason,
            "risk_processed": True,
            "signal_scores": signal_scores,
        }

    latest = history[-1]
    signal_scores: dict[str, int | float] = {
        "escalation_level": compute_escalation_level(
            latest,
            ai_source_used=escalation_source,
            recommendation_source=recommendation_source,
            approval_action=approval_action,
        ),
        "confidence_decay": compute_confidence_decay(
            history,
            ai_confidences=ai_confidences,
            latest_recommendation_source=recommendation_source,
            latest_approval_action=approval_action,
        ),
        "semantic_repetition": compute_semantic_repetition(history),
        "sentiment_trend": compute_sentiment_trend(history),
        "ticket_momentum": compute_ticket_momentum(
            ticket_status=ticket_status,
            latest_activity_at=latest_activity_at,
        ),
    }

    multiplier, multiplier_reason = apply_multiplier(
        history,
        signal_scores,
        escalation_source=escalation_source,
    )
    raw_score = sum(float(value) for value in signal_scores.values())
    final_score = normalize_score(raw_score * multiplier)
    band = map_risk_band(final_score)
    risk_reason = build_risk_reason(signal_scores, multiplier, multiplier_reason)

    # Normalize to numeric(4,3): store as 0.000 - 1.000
    normalized_score = round(final_score / 100.0, 3)

    return {
        "raw_score": raw_score,
        "final_score": final_score,
        "escalation_risk_score": normalized_score,
        "escalation_risk_band": band,
        "confidence_decay_score": float(signal_scores["confidence_decay"]),
        "momentum_score": float(signal_scores["ticket_momentum"]),
        "risk_multiplier": multiplier,
        "risk_reason": risk_reason,
        "risk_processed": True,
        "signal_scores": signal_scores,
    }
