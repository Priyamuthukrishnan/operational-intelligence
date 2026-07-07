"""
backend/intelligence/customer_health.py
Customer Health Scorer. Computes customer health scores based on sentiment,
escalation risk, repeat issue patterns, and resolution rates.
"""

from __future__ import annotations

from typing import Optional

from backend.core.logging import setup_logger

logger = setup_logger(__name__)

# ── Weights for Health Score Components (must sum to 1.0) ──────────────────
_W_SENTIMENT: float = 0.30
_W_ESCALATION: float = 0.30
_W_REPEAT: float = 0.20
_W_RESOLUTION: float = 0.20


class CustomerHealthScorer:
    """Compute customer health score from aggregated operational indicators."""

    @staticmethod
    def calculate_health_score(
        *,
        sentiment_average: Optional[float] = None,
        escalation_risk_average: Optional[float] = None,
        repeat_issue_frequency: Optional[float] = None,
        resolution_rate: Optional[float] = None,
    ) -> float:
        """Calculate a composite customer health score (0.0 to 100.0).

        Args:
            sentiment_average: Average sentiment score [-1.0, 1.0].
            escalation_risk_average: Average escalation risk score [0.0, 1.0].
            repeat_issue_frequency: Ratio of repeat issues [0.0, 1.0].
            resolution_rate: Ratio of resolved tickets [0.0, 1.0].

        Returns:
            A composite score between 0.0 (worst) and 100.0 (best).
        """
        # 1. Sentiment Score Component (range: 0 to 100, neutral is 50)
        if sentiment_average is not None:
            sentiment_average = max(-1.0, min(1.0, sentiment_average))
            s_comp = (sentiment_average + 1.0) / 2.0 * 100.0
        else:
            s_comp = 50.0  # Neutral default

        # 2. Escalation Risk Component (range: 0 to 100, low risk is high health)
        if escalation_risk_average is not None:
            escalation_risk_average = max(0.0, min(1.0, escalation_risk_average))
            e_comp = (1.0 - escalation_risk_average) * 100.0
        else:
            e_comp = 75.0  # Assume moderately low risk default

        # 3. Repeat Issue Component (range: 0 to 100, high repeat frequency is low health)
        if repeat_issue_frequency is not None:
            repeat_issue_frequency = max(0.0, min(1.0, repeat_issue_frequency))
            r_comp = (1.0 - repeat_issue_frequency) * 100.0
        else:
            r_comp = 100.0  # Assumes no repeat issues by default (highest health)

        # 4. Resolution Rate Component (range: 0 to 100, high resolution rate is high health)
        if resolution_rate is not None:
            resolution_rate = max(0.0, min(1.0, resolution_rate))
            res_comp = resolution_rate * 100.0
        else:
            res_comp = 100.0  # Assumes all resolved/no unresolved tickets default

        # Weighted calculation
        composite = (
            _W_SENTIMENT * s_comp
            + _W_ESCALATION * e_comp
            + _W_REPEAT * r_comp
            + _W_RESOLUTION * res_comp
        )

        health_score = max(0.0, min(100.0, round(composite, 2)))

        logger.info(
            "Computed customer health score: %.2f "
            "(sentiment_comp=%.1f, risk_comp=%.1f, repeat_comp=%.1f, resolution_comp=%.1f)",
            health_score,
            s_comp,
            e_comp,
            r_comp,
            res_comp,
        )
        return health_score
