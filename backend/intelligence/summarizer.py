"""
intelligence/summarizer.py
Summarization Engine. Generates concise summaries of customer queries
and resolution actions using LLM inference with offline fallback.
"""

from __future__ import annotations

from typing import Optional

from core.logging import setup_logger
from intelligence.llm_client import LLMClient

logger = setup_logger(__name__)

# Sentinel the model must return verbatim when the input does not
# describe an actual resolution.
_NO_RESOLUTION_MARKER = "NO_RESOLUTION_YET"


class SummarizationEngine:
    """Generates one-sentence summaries for customer queries and resolutions.

    Uses LLM inference when available; falls back to simple text
    truncation otherwise.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    # ── Query summarization ──────────────────────────────────────────────

    def summarize_query(self, text: str) -> Optional[str]:
        """Summarize the customer's problem statement.

        Args:
            text: Raw customer text (typically title + description).

        Returns:
            A one-sentence summary, or ``None`` if the input is empty.
        """
        if not text or not text.strip():
            return None

        prompt = (
            "Summarize the following customer issue in ONE concise sentence.\n"
            "Do not invent details that are not present in the text.\n\n"
            f"{text}"
        )
        output = self._llm.chat(prompt)
        if output is not None:
            return output

        # Offline fallback: truncate
        logger.debug("Using offline fallback for query summarization")
        return text[:150]

    # ── Resolution summarization ─────────────────────────────────────────

    def summarize_resolution(self, text: str) -> Optional[str]:
        """Summarize the actual fix or resolution.

        CRITICAL: if the input is empty or does not describe a real
        resolution, this returns ``None`` — never lets the model invent
        a fix that was never performed.

        Args:
            text: Resolution text (preferably from tickets.resolution).

        Returns:
            A one-sentence summary, or ``None`` if no real resolution
            is described.
        """
        if not text or not text.strip():
            return None

        prompt = (
            "You will be given text describing how a support ticket was "
            "resolved.\nSummarize it in ONE concise sentence, in your "
            "own words.\n\n"
            "RULES:\n"
            "- Only summarize what is literally stated in the text below.\n"
            "- Do NOT invent advice, instructions, or a resolution that "
            "is not present.\n"
            "- If the text does not actually describe a resolution or fix "
            "(for example, if it is just a category label, a status note, "
            "or generic commentary like \"AI identified a similar "
            'incident", with no concrete action described), respond with '
            f"exactly:\n  {_NO_RESOLUTION_MARKER}\n\n"
            f"Text:\n{text}"
        )
        output = self._llm.chat(prompt)

        if output is None:
            # Offline fallback
            logger.debug("Using offline fallback for resolution summarization")
            return text[:150]

        if _NO_RESOLUTION_MARKER in output:
            return None

        return output
