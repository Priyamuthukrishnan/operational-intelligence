"""Deterministic escalation risk scoring utilities (Pure Computation Engine)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.operational_analysis import OperationalAnalysis


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _hours_between(later: datetime, earlier: datetime) -> float:
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


def compute_occurrence_stage(
    signals: dict[str, Any] | None = None,
    history: list[OperationalAnalysis] | None = None,
) -> tuple[str, int]:
    """Determine ticket occurrence stage (MAIN_TICKET, SUB_TICKET, MANAGER_ESCALATED) and count."""
    signals = signals or {}
    history = history or []

    is_manager = bool(signals.get("is_manager_escalated"))
    parent_id = signals.get("parent_ticket_id")
    sub_count = int(signals.get("sub_ticket_count") or 0)

    repeat_count = 0
    if history:
        raw_repeat = _latest_non_null(history, "repeat_count")
        if raw_repeat is not None:
            repeat_count = int(raw_repeat)

    occurrences = max(1, int(signals.get("occurrence_count") or (1 + sub_count if sub_count > 0 else (2 if parent_id else repeat_count))))

    if is_manager or occurrences >= 3:
        return "MANAGER_ESCALATED", max(3, occurrences)
    if parent_id is not None or sub_count > 0 or occurrences == 2:
        return "SUB_TICKET", max(2, occurrences)
    return "MAIN_TICKET", 1


def compute_escalation(
    signals: dict[str, Any] | None = None,
    history: list[OperationalAnalysis] | None = None,
) -> int:
    """Calculate Escalation score based on business lifecycle (Main: 0-10, Sub-ticket: 20, Manager: 35)."""
    signals = signals or {}
    history = history or []
    latest = history[-1] if history else None

    stage, occurrences = compute_occurrence_stage(signals, history)

    if stage == "MANAGER_ESCALATED":
        return 35
    if stage == "SUB_TICKET":
        return 20

    # Main ticket (1st occurrence): 0-10 points base
    ai_source = _norm(signals.get("escalation_source") or getattr(latest, "source_used", None))
    if ai_source in {"manager", "human"}:
        return 10
    if ai_source in {"hybrid", "runbook"}:
        return 5
    return 0


def compute_escalation_level(
    latest: OperationalAnalysis | None,
    ai_source_used: str | None = None,
    recommendation_source: str | None = None,
    approval_action: str | None = None,
) -> int:
    """Legacy helper maintained for backward compatibility."""
    approval_action = _norm(approval_action)
    recommendation_source = _norm(recommendation_source)
    latest_source = _norm(ai_source_used)

    if approval_action in {"escalated", "escalation_requested", "approved", "manager_review"}:
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


def compute_repetition(
    history: list[OperationalAnalysis] | None = None,
    signals: dict[str, Any] | None = None,
) -> int:
    """Calculate Repetition score based on repeat count or sub-ticket count."""
    history = history or []
    signals = signals or {}

    sub_count = int(signals.get("sub_ticket_count") or 0)
    repeat_count = 0

    if history:
        raw_repeat = _latest_non_null(history, "repeat_count")
        if raw_repeat is not None:
            repeat_count = int(raw_repeat)

    count = max(repeat_count, sub_count)
    if count <= 0:
        return 0
    if count == 1:
        return 6
    if count <= 3:
        return 12
    return 20


def compute_semantic_repetition(history: list[OperationalAnalysis]) -> int:
    """Legacy helper maintained for backward compatibility."""
    return compute_repetition(history)


def compute_sentiment(
    history: list[OperationalAnalysis] | None = None,
    signals: dict[str, Any] | None = None,
) -> int:
    """Calculate Sentiment score based on polarity trends."""
    history = history or []
    signals = signals or {}

    sentiment = None
    if history:
        sentiment = _latest_non_null(history, "sentiment_score")
    if sentiment is None and "sentiment_score" in signals:
        sentiment = signals.get("sentiment_score")

    if sentiment is None:
        return 0

    try:
        val = float(sentiment)
        if val >= 0:
            return 0
        if val >= -0.20:
            return 4
        if val >= -0.40:
            return 9
        return 15
    except (TypeError, ValueError):
        return 0


def compute_sentiment_trend(history: list[OperationalAnalysis]) -> int:
    """Legacy helper maintained for backward compatibility."""
    return compute_sentiment(history)


def compute_confidence(
    history: list[OperationalAnalysis] | None = None,
    signals: dict[str, Any] | None = None,
) -> float:
    """Calculate Confidence Decay score or initial baseline confidence score."""
    history = history or []
    signals = signals or {}

    root_confidences = [
        row.root_cause_confidence
        for row in history
        if row.root_cause_confidence is not None
    ]
    ai_confidences = [
        float(v)
        for v in (signals.get("ai_confidences") or [])
        if v is not None
    ]

    source_history = root_confidences if len(root_confidences) >= 2 else ai_confidences

    if len(source_history) >= 2:
        oldest = source_history[0]
        latest = source_history[-1]
        delta = latest - oldest
        decay = max(0.0, -delta * 40.0)

        action = _norm(signals.get("approval_action"))
        if action in {"denied", "rejected", "escalation_requested"}:
            decay += 3.0
        return round(min(decay, 20.0), 2)

    # Initial baseline estimation for single snapshot / new tickets
    initial_conf = signals.get("initial_ai_confidence")
    if initial_conf is None and history:
        initial_conf = _latest_non_null(history, "root_cause_confidence")

    if initial_conf is not None:
        try:
            val = float(initial_conf)
            if 0.0 <= val <= 1.0:
                baseline_decay = max(0.0, round((1.0 - val) * 8.0, 2))
                return min(baseline_decay, 10.0)
            return round(val, 2)
        except (TypeError, ValueError):
            pass

    return 2.0


def compute_confidence_decay(
    history: list[OperationalAnalysis],
    ai_confidences: list[float] | None = None,
    latest_recommendation_source: str | None = None,
    latest_approval_action: str | None = None,
) -> float:
    """Legacy helper maintained for backward compatibility."""
    signals = {
        "ai_confidences": ai_confidences,
        "approval_action": latest_approval_action,
    }
    return compute_confidence(history, signals)


def compute_momentum(
    signals: dict[str, Any] | None = None,
    history: list[OperationalAnalysis] | None = None,
    ticket_status: str | None = None,
    latest_activity_at: datetime | None = None,
) -> int:
    """Calculate rich operational momentum considering inactivity, SLA, follow-ups, comments, and sub-tickets."""
    signals = signals or {}
    status = _norm(signals.get("ticket_status") or ticket_status)
    if status in {"resolved", "closed", "cancelled"}:
        return 0

    act_at = signals.get("latest_activity_at") or latest_activity_at
    if act_at is None:
        activity_score = 0
    else:
        age_hours = _hours_between(datetime.now(timezone.utc), act_at)
        if age_hours < 12.0:
            activity_score = 0
        elif age_hours < 24.0:
            activity_score = 5
        elif age_hours < 48.0:
            activity_score = 12
        else:
            activity_score = 18

    # Contributors to operational urgency
    sla_score = 10 if bool(signals.get("sla_breached")) else 0
    follow_up_count = int(signals.get("follow_up_count") or 0)
    follow_up_score = min(9, follow_up_count * 3)
    reassignment_score = 4 if int(signals.get("reassignment_count") or 0) > 1 else 0
    sub_ticket_score = 3 if int(signals.get("sub_ticket_count") or 0) > 0 else 0

    # Comment engagement: active discussion signals ongoing operational attention
    comment_count = int(signals.get("comment_count") or 0)
    comment_score = 0
    if comment_count >= 10:
        comment_score = 5
    elif comment_count >= 5:
        comment_score = 3
    elif comment_count >= 2:
        comment_score = 1

    total_momentum = activity_score + sla_score + follow_up_score + reassignment_score + sub_ticket_score + comment_score
    return min(30, total_momentum)


def compute_ticket_momentum(
    ticket_status: str | None = None,
    latest_activity_at: datetime | None = None,
) -> int:
    """Legacy helper maintained for backward compatibility."""
    return compute_momentum(signals={"ticket_status": ticket_status, "latest_activity_at": latest_activity_at})


def compute_multiplier(
    history: list[OperationalAnalysis] | None = None,
    signal_scores: dict[str, int | float] | None = None,
    signals: dict[str, Any] | None = None,
    escalation_source: str | None = None,
) -> tuple[float, str]:
    """Calculate risk multiplier based on compound risk rules including priority."""
    signal_scores = signal_scores or {}
    signals = signals or {}

    escalation_level = int(signal_scores.get("escalation_level", 0))
    confidence_decay = float(signal_scores.get("confidence_decay", 0.0))
    repetition = int(signal_scores.get("semantic_repetition", 0))
    sentiment = int(signal_scores.get("sentiment_trend", 0))
    momentum = int(signal_scores.get("ticket_momentum", 0))
    priority = _norm(signals.get("priority"))

    if escalation_level >= 35 or bool(signals.get("is_manager_escalated")):
        return 1.35, "Manager escalation active"
    if bool(signals.get("sla_breached")) and momentum >= 12:
        return 1.30, "SLA breach with high momentum"
    if sentiment > 0 and momentum >= 12:
        return 1.30, "Negative sentiment with operational stagnation"
    if priority in {"high", "urgent", "critical"} and momentum >= 10:
        return 1.25, "High priority with elevated operational momentum"
    if confidence_decay >= 6.0 and repetition >= 6:
        return 1.25, "Confidence decay with repeated occurrences"

    return 1.0, "none"


def apply_multiplier(
    history: list[OperationalAnalysis],
    signal_scores: dict[str, int | float],
    escalation_source: str | None = None,
) -> tuple[float, str]:
    """Legacy helper maintained for backward compatibility."""
    return compute_multiplier(history, signal_scores, escalation_source=escalation_source)


def normalize_score(score: float) -> int:
    return max(0, min(100, round(score)))


def map_risk_band(score: int) -> str:
    if score <= 24:
        return "LOW"
    if score <= 49:
        return "MEDIUM"
    if score <= 74:
        return "HIGH"
    return "CRITICAL"


def generate_recommendation(
    risk_band: str,
    stage: str,
    occurrences: int,
    sub_tickets: int,
    sla_breached: bool,
    sentiment_score: float | None,
    signals: dict[str, Any],
) -> tuple[str, list[str]]:
    """Generate one Primary Recommendation and supporting context observations from real operational data."""
    priority = _norm(signals.get("priority"))
    comment_count = int(signals.get("comment_count") or 0)
    follow_up_count = int(signals.get("follow_up_count") or 0)
    reassignment_count = int(signals.get("reassignment_count") or 0)
    approval_action = _norm(signals.get("approval_action"))

    # 1. Determine single Primary Recommendation (the single most important action for manager)
    if risk_band == "CRITICAL" or stage == "MANAGER_ESCALATED" or bool(signals.get("is_manager_escalated")):
        primary = "Immediate manager review required."
    elif sla_breached:
        primary = "Follow up immediately to address SLA breach."
    elif risk_band == "HIGH":
        primary = "Assign to L2 support immediately."
    elif stage == "SUB_TICKET" or sub_tickets > 0 or occurrences >= 2:
        primary = "Investigate root cause prior to ticket closure."
    elif sentiment_score is not None and sentiment_score < -0.3:
        primary = "Engage customer directly to address sentiment friction."
    else:
        primary = "Continue normal SLA handling."

    # 2. Gather Supporting Observations
    observations: list[str] = []
    if occurrences >= 2:
        observations.append(f"Customer reported this issue {occurrences} times.")
    if sub_tickets > 0:
        observations.append(f"{sub_tickets} linked sub-ticket(s) already created.")
    if sla_breached:
        observations.append("SLA commitment has been breached.")
    
    act_at = signals.get("latest_activity_at")
    if act_at is not None:
        try:
            age_hours = _hours_between(datetime.now(timezone.utc), act_at)
            if age_hours >= 24.0:
                observations.append(f"Ticket has remained inactive for {round(age_hours, 1)} hours.")
        except (TypeError, ValueError):
            pass

    if follow_up_count >= 2:
        observations.append(f"{follow_up_count} customer follow-up interactions recorded.")
    if reassignment_count > 1:
        observations.append(f"Ticket has been reassigned {reassignment_count} times.")
    if comment_count >= 5:
        observations.append(f"Active discussion with {comment_count} comments recorded.")
    if priority in {"high", "urgent", "critical"}:
        observations.append(f"Ticket priority is set to {priority.upper()}.")
    if approval_action in {"denied", "rejected"}:
        observations.append("Previous manager approval action was denied.")
    if sentiment_score is not None and sentiment_score < -0.3:
        observations.append("Customer sentiment is notably negative.")

    return primary, observations


def build_operational_insight(
    stage: str,
    occurrences: int,
    sub_tickets: int,
    risk_band: str,
    sla_breached: bool,
    confidence_decay: float,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate business-language operational insight from available operational data."""
    signals = signals or {}
    top_factors: list[str] = []

    # Core lifecycle factors in business terminology
    if occurrences >= 2:
        top_factors.append(f"Repeated customer issue ({occurrences} occurrences)")
    if sub_tickets > 0:
        top_factors.append(f"{sub_tickets} linked sub-ticket(s) created")
    if stage == "MANAGER_ESCALATED" or bool(signals.get("is_manager_escalated")):
        top_factors.append("Manager escalation active")
    if sla_breached:
        top_factors.append("SLA breached")

    priority = _norm(signals.get("priority"))
    if priority in {"high", "urgent", "critical"}:
        top_factors.append(f"High ticket priority ({priority.upper()})")

    reassignment_count = int(signals.get("reassignment_count") or 0)
    if reassignment_count > 1:
        top_factors.append(f"Multiple reassignments ({reassignment_count} times)")

    follow_up_count = int(signals.get("follow_up_count") or 0)
    if follow_up_count >= 2:
        top_factors.append(f"Frequent customer follow-ups ({follow_up_count})")

    comment_count = int(signals.get("comment_count") or 0)
    if comment_count >= 5:
        top_factors.append(f"Active discussion thread ({comment_count} comments)")

    if not top_factors:
        top_factors.append("Standard operational SLA progress")

    # High-level narrative summary explaining why the ticket requires attention in business language
    if stage == "MANAGER_ESCALATED" or risk_band == "CRITICAL" or bool(signals.get("is_manager_escalated")):
        title = "Manager Review Required"
        summary = f"Customer issue has escalated to manager review after {occurrences} occurrence(s) and requires resolution oversight."
    elif sub_tickets > 0 or occurrences >= 2:
        title = "Repeated Customer Issue"
        summary = f"Customer reported this issue multiple times with {sub_tickets} linked sub-ticket(s) requiring root cause investigation."
    elif sla_breached:
        title = "SLA Compliance Risk"
        summary = "Ticket has breached SLA commitment and requires immediate operational intervention."
    elif risk_band == "HIGH":
        title = "High Risk Escalation Signal"
        summary = "Operational urgency is elevated due to customer follow-ups and activity delays."
    else:
        title = "Standard Ticket Progress"
        summary = "Ticket is proceeding normally under standard SLA guidelines."

    return {
        "title": title,
        "summary": summary,
        "top_factors": top_factors,
    }


def _compute_ticket_age_hours(signals: dict[str, Any]) -> float | None:
    """Calculate ticket age in hours from earliest available timestamp."""
    act_at = signals.get("latest_activity_at")
    if act_at is None:
        return None
    try:
        return round(_hours_between(datetime.now(timezone.utc), act_at), 1)
    except (TypeError, ValueError):
        return None


def _build_activity_summary(signals: dict[str, Any]) -> str | None:
    """Build a short activity summary string from available operational counts."""
    comment_count = int(signals.get("comment_count") or 0)
    follow_up_count = int(signals.get("follow_up_count") or 0)
    reassignment_count = int(signals.get("reassignment_count") or 0)

    # Only produce a summary if any data is present
    if comment_count == 0 and follow_up_count == 0 and reassignment_count == 0:
        return None

    parts = []
    parts.append(f"{comment_count} comment(s)")
    if follow_up_count > 0:
        parts.append(f"{follow_up_count} follow-up(s)")
    if reassignment_count > 0:
        parts.append(f"{reassignment_count} reassignment(s)")
    return ", ".join(parts)


def _lifecycle_stage_label(stage: str) -> str:
    """Map internal stage constant to human-readable lifecycle label."""
    return {
        "MAIN_TICKET": "First Occurrence",
        "SUB_TICKET": "Repeat Issue – Sub-ticket",
        "MANAGER_ESCALATED": "Manager Escalation",
    }.get(stage, stage)


def build_business_view(
    final_score: int,
    risk_band: str,
    stage: str,
    occurrences: int,
    sub_tickets: int,
    sentiment_label: str,
    sla_breached: bool,
    confidence_decay: float,
    recommendation: str,
    supporting_observations: list[str] | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the clean business object for business users and managers."""
    signals = signals or {}
    supporting_observations = supporting_observations or []
    manager_status = "Escalated" if (stage == "MANAGER_ESCALATED" or bool(signals.get("is_manager_escalated"))) else ("Pending Review" if risk_band in {"HIGH", "CRITICAL"} else "Not Required")

    insight = build_operational_insight(
        stage=stage,
        occurrences=occurrences,
        sub_tickets=sub_tickets,
        risk_band=risk_band,
        sla_breached=sla_breached,
        confidence_decay=confidence_decay,
        signals=signals,
    )

    priority = signals.get("priority")
    ticket_age = _compute_ticket_age_hours(signals)
    activity_summary = _build_activity_summary(signals)

    view: dict[str, Any] = {
        "overall_risk": {
            "score": final_score,
            "band": risk_band,
        },
        "incident_history": {
            "repeated_issue": occurrences >= 2 or sub_tickets > 0,
            "occurrences": occurrences,
            "sub_tickets": sub_tickets,
        },
        "customer_sentiment": {
            "label": sentiment_label or "Neutral",
        },
        "manager_escalation": {
            "status": manager_status,
        },
        "operational_insight": insight,
        "recommendation": recommendation,
        "primary_recommendation": recommendation,
        "supporting_observations": supporting_observations,
        "lifecycle_stage": _lifecycle_stage_label(stage),
    }

    # Optional fields — only include when data is available
    if priority:
        view["priority"] = str(priority).upper()
    if ticket_age is not None:
        view["ticket_age_hours"] = ticket_age
    if activity_summary:
        view["activity_summary"] = activity_summary

    return view


def build_risk_reason(
    signal_scores: dict[str, int | float],
    multiplier: float,
    multiplier_reason: str,
    recommendation: str | None = None,
    business_view: dict[str, Any] | None = None,
) -> dict:
    """Build risk_reason dict containing both engineering signals and business view."""
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
        "multiplier": multiplier,
    }
    if multiplier_reason and multiplier_reason != "none":
        reason["multiplier_reason"] = multiplier_reason

    if recommendation:
        reason["recommendation"] = recommendation

    if business_view:
        reason["business"] = business_view
        reason["summary"] = business_view.get("operational_insight", {}).get("summary")
        reason["reasons"] = business_view.get("operational_insight", {}).get("top_factors")

    return reason


def compute(
    history: list[OperationalAnalysis],
    escalation_source: str | None = None,
    recommendation_source: str | None = None,
    approval_action: str | None = None,
    ai_confidences: list[float] | None = None,
    ticket_status: str | None = None,
    latest_activity_at: datetime | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute risk score and assemble both engineering and business view results."""
    signals = signals or {}
    if escalation_source and "escalation_source" not in signals:
        signals["escalation_source"] = escalation_source
    if approval_action and "approval_action" not in signals:
        signals["approval_action"] = approval_action
    if ai_confidences and "ai_confidences" not in signals:
        signals["ai_confidences"] = ai_confidences
    if ticket_status and "ticket_status" not in signals:
        signals["ticket_status"] = ticket_status
    if latest_activity_at and "latest_activity_at" not in signals:
        signals["latest_activity_at"] = latest_activity_at

    latest = history[-1] if history else None
    sentiment_label = getattr(latest, "sentiment_label", None) or "Neutral"
    sentiment_score = getattr(latest, "sentiment_score", None)
    if sentiment_score is not None and "sentiment_score" not in signals:
        signals["sentiment_score"] = sentiment_score

    stage, occurrences = compute_occurrence_stage(signals, history)
    sub_tickets = int(signals.get("sub_ticket_count") or (occurrences - 1 if occurrences > 1 else 0))

    signal_scores: dict[str, int | float] = {
        "escalation_level": compute_escalation(signals, history),
        "confidence_decay": compute_confidence(history, signals),
        "semantic_repetition": compute_repetition(history, signals),
        "sentiment_trend": compute_sentiment(history, signals),
        "ticket_momentum": compute_momentum(signals, history),
    }

    multiplier, multiplier_reason = compute_multiplier(history, signal_scores, signals, escalation_source=escalation_source)
    raw_score = sum(float(v) for v in signal_scores.values())
    final_score = normalize_score(raw_score * multiplier)
    band = map_risk_band(final_score)

    sla_breached = bool(signals.get("sla_breached"))
    primary_recommendation, supporting_observations = generate_recommendation(
        risk_band=band,
        stage=stage,
        occurrences=occurrences,
        sub_tickets=sub_tickets,
        sla_breached=sla_breached,
        sentiment_score=sentiment_score,
        signals=signals,
    )

    business_view = build_business_view(
        final_score=final_score,
        risk_band=band,
        stage=stage,
        occurrences=occurrences,
        sub_tickets=sub_tickets,
        sentiment_label=sentiment_label,
        sla_breached=sla_breached,
        confidence_decay=float(signal_scores["confidence_decay"]),
        recommendation=primary_recommendation,
        supporting_observations=supporting_observations,
        signals=signals,
    )

    risk_reason = build_risk_reason(
        signal_scores=signal_scores,
        multiplier=multiplier,
        multiplier_reason=multiplier_reason,
        recommendation=primary_recommendation,
        business_view=business_view,
    )

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
        "business": business_view,
        "risk_processed": True,
        "signal_scores": signal_scores,
    }

