"""Deterministic escalation risk scoring utilities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.models.operational_analysis import OperationalAnalysis


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _hours_between(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return max((later - earlier).total_seconds() / 3600.0, 0.0)


def _latest_non_null(history: list[OperationalAnalysis], attr: str) -> Any:
    for row in reversed(history):
        value = getattr(row, attr, None)
        if value is not None:
            return value
    return None


def compute_escalation_level(latest: OperationalAnalysis) -> int:
    source_used = _norm(latest.source_used)

    if source_used == "manager" or latest.assigned_manager_id is not None:
        return 35
    if source_used == "human" or latest.assigned_agent_id is not None:
        return 28
    if source_used == "hybrid":
        return 18
    if source_used == "runbook":
        return 10
    return 0


def compute_confidence_decay(history: list[OperationalAnalysis]) -> float:
    confidences = [
        row.root_cause_confidence
        for row in history
        if row.root_cause_confidence is not None
    ]
    if len(confidences) < 2:
        return 0.0

    oldest = confidences[0]
    latest = confidences[-1]
    delta = latest - oldest
    decay = max(0.0, -delta * 40.0)
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


def compute_ticket_momentum(history: list[OperationalAnalysis]) -> int:
    if not history:
        return 0

    latest = history[-1]
    latest_state = _norm(latest.resolution_state)
    latest_source = _norm(latest.source_used)
    latest_ts = latest.captured_at
    previous_ts = history[-2].captured_at if len(history) > 1 else None
    earliest_ts = history[0].captured_at

    if latest_state in {"resolved", "closed"}:
        return 0

    gap_hours = _hours_between(latest_ts, previous_ts)
    age_hours = _hours_between(latest_ts, earliest_ts)
    elapsed = gap_hours if gap_hours is not None else age_hours

    if latest_source in {"human", "manager"} and (
        elapsed is None or elapsed >= 24.0
    ):
        return 20

    if elapsed is None:
        return 0
    if elapsed < 12.0:
        return 0
    if elapsed < 24.0:
        return 5
    if elapsed < 48.0:
        return 12
    return 18


def apply_multiplier(
    history: list[OperationalAnalysis],
    signal_scores: dict[str, int | float],
) -> tuple[float, str]:
    latest = history[-1] if history else None
    if latest is None:
        return 1.0, "none"

    source_used = _norm(latest.source_used)
    escalation_level = int(signal_scores.get("escalation_level", 0))
    confidence_decay = float(signal_scores.get("confidence_decay", 0.0))
    repetition = int(signal_scores.get("semantic_repetition", 0))
    sentiment = int(signal_scores.get("sentiment_trend", 0))
    momentum = int(signal_scores.get("ticket_momentum", 0))

    gap_hours = _hours_between(
        latest.captured_at,
        history[-2].captured_at if len(history) > 1 else history[0].captured_at,
    )

    candidates: list[tuple[float, str, bool]] = [
        (
            1.35,
            "human escalation with no progress >48h",
            escalation_level >= 28
            and source_used in {"human", "manager"}
            and (gap_hours is not None and gap_hours > 48.0),
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
) -> str:
    parts = [
        f"level={signal_scores.get('escalation_level', 0)}",
        f"confidence_decay={signal_scores.get('confidence_decay', 0)}",
        f"repetition={signal_scores.get('semantic_repetition', 0)}",
        f"sentiment={signal_scores.get('sentiment_trend', 0)}",
        f"momentum={signal_scores.get('ticket_momentum', 0)}",
        f"multiplier={multiplier:.2f}",
    ]
    if multiplier_reason != "none":
        parts.append(multiplier_reason)
    return "; ".join(parts)


def compute(history: list[OperationalAnalysis]) -> dict[str, Any]:
    if not history:
        return {
            "raw_score": 0,
            "final_score": 0,
            "escalation_risk_score": 0,
            "escalation_risk_band": "LOW",
            "confidence_decay_score": 0.0,
            "momentum_score": 0.0,
            "risk_multiplier": 1.0,
            "risk_reason": "no history",
            "risk_processed": True,
            "signal_scores": {
                "escalation_level": 0,
                "confidence_decay": 0.0,
                "semantic_repetition": 0,
                "sentiment_trend": 0,
                "ticket_momentum": 0,
            },
        }

    latest = history[-1]
    signal_scores: dict[str, int | float] = {
        "escalation_level": compute_escalation_level(latest),
        "confidence_decay": compute_confidence_decay(history),
        "semantic_repetition": compute_semantic_repetition(history),
        "sentiment_trend": compute_sentiment_trend(history),
        "ticket_momentum": compute_ticket_momentum(history),
    }

    multiplier, multiplier_reason = apply_multiplier(history, signal_scores)
    raw_score = sum(float(value) for value in signal_scores.values())
    final_score = normalize_score(raw_score * multiplier)
    band = map_risk_band(final_score)
    risk_reason = build_risk_reason(signal_scores, multiplier, multiplier_reason)

    return {
        "raw_score": raw_score,
        "final_score": final_score,
        "escalation_risk_score": float(final_score),
        "escalation_risk_band": band,
        "confidence_decay_score": float(signal_scores["confidence_decay"]),
        "momentum_score": float(signal_scores["ticket_momentum"]),
        "risk_multiplier": multiplier,
        "risk_reason": risk_reason,
        "risk_processed": True,
        "signal_scores": signal_scores,
    }
