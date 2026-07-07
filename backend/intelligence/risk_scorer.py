"""
backend/intelligence/risk_scorer.py
Escalation Risk Scorer. Evaluates interaction features to compute an
escalation-risk probability and risk-band classification.

Uses a weighted rule-based model that combines:
  - Sentiment polarity       (35 %)
  - Repeat-issue frequency   (25 %)
  - Resolution availability  (20 %)
  - Root-cause severity       (20 %)

No external ML model is required — the scorer runs entirely offline.
"""

from __future__ import annotations

from typing import Optional

from backend.core.logging import setup_logger

logger = setup_logger(__name__)

# ── Weight configuration ─────────────────────────────────────────────────

_W_SENTIMENT: float = 0.35
_W_REPEAT: float = 0.25
_W_RESOLUTION: float = 0.20
_W_ROOT_CAUSE: float = 0.20

# ── Root-cause categories that indicate higher escalation risk ───────────

_HIGH_RISK_CATEGORIES = frozenset({
    "infrastructure_issue",
    "security_concern",
    "integration_failure",
    "performance_degradation",
    "data_loss",
})

# ── Risk-band thresholds ─────────────────────────────────────────────────

_BAND_THRESHOLDS: list[tuple[float, str]] = [
    (0.75, "critical"),
    (0.50, "high"),
    (0.25, "medium"),
    (0.00, "low"),
]


class EscalationRiskScorer:
    """Compute escalation-risk score and band for an interaction.

    All inputs are optional — missing values are treated as neutral
    (contribute 0.0 to the weighted sum).  This makes the scorer safe
    to call even on partially-enriched records.
    """

    def score(
        self,
        *,
        sentiment_label: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        repeat_count: Optional[int] = None,
        has_resolution: bool = True,
        root_cause_category: Optional[str] = None,
    ) -> tuple[float, str]:
        """Compute the escalation-risk score.

        Args:
            sentiment_label: ``"positive"``, ``"neutral"``, or ``"negative"``.
            sentiment_score: Score in ``[-1.0, 1.0]``.
            repeat_count: How many times the issue has recurred.
            has_resolution: ``False`` if no resolution exists yet.
            root_cause_category: Predicted root-cause category string.

        Returns:
            A ``(score, band)`` tuple where score is in ``[0.0, 1.0]``
            and band is one of ``"low"``, ``"medium"``, ``"high"``,
            ``"critical"``.
        """
        # ── Sentiment factor (negative → higher risk) ────────────────────
        sentiment_factor = 0.0
        if sentiment_score is not None:
            # Map [-1, 1] → [1, 0] so that negative sentiment = high risk
            sentiment_factor = (1.0 - sentiment_score) / 2.0
        elif sentiment_label is not None:
            sentiment_factor = {
                "negative": 0.8,
                "neutral": 0.4,
                "positive": 0.1,
            }.get(sentiment_label.lower(), 0.4)

        # ── Repeat factor (more repeats → higher risk) ───────────────────
        repeat_factor = 0.0
        if repeat_count is not None and repeat_count > 0:
            # Saturating curve: 1 repeat → 0.4, 3 → 0.8, 5+ → ~1.0
            repeat_factor = min(1.0, repeat_count * 0.2)

        # ── Resolution factor (unresolved → higher risk) ─────────────────
        resolution_factor = 0.0 if has_resolution else 1.0

        # ── Root-cause severity factor ───────────────────────────────────
        root_cause_factor = 0.0
        if root_cause_category is not None:
            if root_cause_category.lower() in _HIGH_RISK_CATEGORIES:
                root_cause_factor = 0.8
            else:
                root_cause_factor = 0.3

        # ── Weighted composite ───────────────────────────────────────────
        raw_score = (
            _W_SENTIMENT * sentiment_factor
            + _W_REPEAT * repeat_factor
            + _W_RESOLUTION * resolution_factor
            + _W_ROOT_CAUSE * root_cause_factor
        )

        # Clamp to [0, 1]
        score = max(0.0, min(1.0, round(raw_score, 4)))

        # ── Band classification ──────────────────────────────────────────
        band = "low"
        for threshold, label in _BAND_THRESHOLDS:
            if score >= threshold:
                band = label
                break

        logger.debug(
            "Escalation risk: score=%.4f band=%s "
            "(sentiment=%.2f repeat=%.2f resolution=%.2f root_cause=%.2f)",
            score,
            band,
            sentiment_factor,
            repeat_factor,
            resolution_factor,
            root_cause_factor,
        )
        return score, band
