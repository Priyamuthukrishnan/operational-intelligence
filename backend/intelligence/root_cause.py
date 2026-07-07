"""
backend/intelligence/root_cause.py
Root Cause Engine. Classifies the root cause of a customer issue into
a predefined taxonomy using LLM inference with offline fallback.
"""

from __future__ import annotations

from typing import Optional

from backend.core.logging import setup_logger
from backend.intelligence.llm_client import LLMClient

logger = setup_logger(__name__)

# ── Predefined root-cause taxonomy ───────────────────────────────────────

ROOT_CAUSE_CATEGORIES = [
    "software_bug",
    "configuration_error",
    "user_error",
    "infrastructure_issue",
    "integration_failure",
    "performance_degradation",
    "security_concern",
    "documentation_gap",
    "feature_request",
    "billing_issue",
    "access_permission",
    "data_issue",
    "unknown",
]

_CATEGORIES_STR = ", ".join(ROOT_CAUSE_CATEGORIES)


class RootCauseEngine:
    """Classify the root cause of a customer issue.

    Uses LLM inference to map the issue description to one of the
    predefined categories with a confidence score.  Falls back to
    keyword matching when the LLM is unavailable.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def analyze(self, text: str) -> tuple[Optional[str], Optional[float]]:
        """Analyse the root cause of a customer issue.

        Args:
            text: Issue description text (ideally the query_summary or
                raw customer text).

        Returns:
            A ``(category, confidence)`` tuple.  ``category`` is one
            of :data:`ROOT_CAUSE_CATEGORIES`.  ``confidence`` is in
            ``[0.0, 1.0]``.  Both are ``None`` if the input is empty.
        """
        if not text or not text.strip():
            return None, None

        prompt = (
            "You are a support-issue root-cause classifier.\n"
            "Classify the following customer issue into exactly ONE "
            "of these categories:\n"
            f"  {_CATEGORIES_STR}\n\n"
            "Return ONLY valid JSON, no commentary:\n"
            '{"category":"<category>","confidence":0.0}\n\n'
            "Rules:\n"
            "- confidence is a float between 0.0 and 1.0\n"
            "- If unsure, use category 'unknown' with a low confidence\n"
            "- Do NOT invent categories outside the list\n\n"
            f"Issue Text:\n{text}"
        )
        data = self._llm.chat_json(prompt)

        if data is not None:
            try:
                category = str(data["category"]).lower().strip()
                confidence = float(data["confidence"])
                confidence = max(0.0, min(1.0, confidence))
                # Validate category against taxonomy
                if category not in ROOT_CAUSE_CATEGORIES:
                    logger.warning(
                        "LLM returned unknown category '%s' — "
                        "mapping to 'unknown'",
                        category,
                    )
                    category = "unknown"
                    confidence = max(confidence * 0.5, 0.1)
                return category, round(confidence, 4)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "Invalid root-cause JSON structure: %s — "
                    "falling back to offline analysis",
                    exc,
                )

        # Offline fallback
        return self._fallback_classify(text)

    # ── Offline fallback ─────────────────────────────────────────────────

    @staticmethod
    def _fallback_classify(
        text: str,
    ) -> tuple[str, float]:
        """Keyword-based root-cause classification when LLM is unavailable."""
        lower = text.lower()

        keyword_map: list[tuple[list[str], str]] = [
            (["bug", "crash", "error", "exception", "stack trace"], "software_bug"),
            (["config", "configuration", "setting", "misconfigur"], "configuration_error"),
            (["permission", "access", "denied", "forbidden", "role"], "access_permission"),
            (["slow", "latency", "timeout", "performance", "lag"], "performance_degradation"),
            (["integration", "api", "webhook", "sync", "connector"], "integration_failure"),
            (["infrastructure", "server", "downtime", "outage", "cluster"], "infrastructure_issue"),
            (["security", "vulnerability", "breach", "attack", "ssl"], "security_concern"),
            (["documentation", "docs", "guide", "unclear", "how to"], "documentation_gap"),
            (["feature", "enhancement", "request", "wish", "add support"], "feature_request"),
            (["billing", "invoice", "charge", "payment", "subscription"], "billing_issue"),
            (["data", "missing data", "corrupt", "lost", "incorrect data"], "data_issue"),
            (["user error", "mistake", "wrong input", "accidentally"], "user_error"),
        ]

        for keywords, category in keyword_map:
            if any(kw in lower for kw in keywords):
                return category, 0.5

        return "unknown", 0.2
