"""
backend/intelligence/sentiment.py
Sentiment Engine. Analyses the emotional tone of customer interactions
and returns a classification label with a calibrated score.
"""

from __future__ import annotations

from typing import Optional

from backend.core.logging import setup_logger
from backend.intelligence.llm_client import LLMClient

logger = setup_logger(__name__)


class SentimentEngine:
    """Classify customer sentiment using LLM analysis with offline fallback.

    The engine analyses ONLY the customer's emotional tone — it does not
    factor in system status or ticket outcomes. A calm bug report should
    score near neutral; only frustration, anger, or repeated complaints
    should score strongly negative.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, text: str) -> tuple[str, float]:
        """Analyse customer sentiment.

        Args:
            text: Customer-authored text (title + description + comments).

        Returns:
            A ``(label, score)`` tuple where label is one of
            ``"positive"``, ``"neutral"``, ``"negative"`` and score
            is in the range ``[-1.0, 1.0]``.
        """
        if not text or not text.strip():
            return "neutral", 0.0

        prompt = (
            "Analyze ONLY the customer's sentiment in the text below.\n"
            "Calibrate the score honestly — do not default to a strong "
            "negative score just because the message describes a problem. "
            "A calm bug report is closer to neutral; only frustration, "
            "anger, or repeated complaints should score strongly negative.\n\n"
            "Return ONLY valid JSON, no commentary:\n"
            '{"label":"positive|neutral|negative","score":0.0}\n\n'
            f"Customer Text:\n{text}"
        )
        data = self._llm.chat_json(prompt)

        if data is not None:
            try:
                label = str(data["label"]).lower()
                score = float(data["score"])
                # Clamp score to valid range
                score = max(-1.0, min(1.0, score))
                if label not in ("positive", "neutral", "negative"):
                    label = "neutral"
                return label, score
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "Invalid sentiment JSON structure: %s — "
                    "falling back to offline analysis",
                    exc,
                )

        # Offline fallback
        return self._fallback_sentiment(text)

    # ── Offline fallback ─────────────────────────────────────────────────

    @staticmethod
    def _fallback_sentiment(text: str) -> tuple[str, float]:
        """Rule-based sentiment scoring when LLM is unavailable."""
        lower = text.lower()

        positive_words = [
            "thank", "thanks", "great", "perfect", "resolved", "fixed",
            "awesome", "appreciate", "worked", "excellent", "happy",
        ]
        negative_words = [
            "frustrating", "waiting", "not working", "error", "failed",
            "issue", "problem", "slow", "escalate", "third time",
            "unacceptable", "angry", "terrible", "broken", "urgent",
        ]

        pos_count = sum(1 for w in positive_words if w in lower)
        neg_count = sum(1 for w in negative_words if w in lower)
        raw_score = pos_count - neg_count

        if raw_score > 0:
            return "positive", min(raw_score / 5.0, 1.0)
        if raw_score < 0:
            return "negative", max(raw_score / 5.0, -1.0)
        return "neutral", 0.0
