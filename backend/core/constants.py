"""
backend/core/constants.py
Domain-wide system constants, risk scoring thresholds, and classification labels.
"""

# ── Sentiment scoring bounds ─────────────────────────────────────────────
SENTIMENT_SCORE_MIN: float = -1.0
SENTIMENT_SCORE_MAX: float = 1.0

# ── Escalation risk scoring bounds ───────────────────────────────────────
ESCALATION_RISK_SCORE_MIN: float = 0.0
ESCALATION_RISK_SCORE_MAX: float = 1.0

# ── Repeat count minimum ────────────────────────────────────────────────
REPEAT_COUNT_MIN: int = 0
