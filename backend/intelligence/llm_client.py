"""
intelligence/llm_client.py
Shared LLM client wrapper. Provides a single reusable interface for all
intelligence modules that need LLM inference (summarization, sentiment,
root-cause analysis, etc.).

Uses Mistral AI when MISTRAL_API_KEY is configured; gracefully returns
None when no API key is available so callers can apply offline fallbacks.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from core.config import get_settings
from core.logging import setup_logger

logger = setup_logger(__name__)

# Default delay between consecutive LLM calls to avoid rate-limit errors.
_DEFAULT_CALL_DELAY: float = 0.5


class LLMClient:
    """Thread-safe, reusable wrapper around the Mistral chat API.

    Instantiate once and pass to all intelligence modules that require
    LLM inference.  When ``MISTRAL_API_KEY`` is not set the client is
    created in *offline mode* — every call returns ``None`` so that
    callers can apply their own fallback logic.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key: Optional[str] = settings.MISTRAL_API_KEY
        self._model: str = settings.LLM_MODEL
        self._client: Optional[Any] = None

        if self._api_key:
            try:
                try:
                    from mistralai import Mistral
                except ImportError:
                    from mistralai.client import Mistral

                self._client = Mistral(api_key=self._api_key)
                logger.info(
                    "LLMClient initialised with model=%s", self._model
                )
            except ImportError:
                logger.warning(
                    "mistralai package not installed — running in "
                    "offline mode"
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialise Mistral client: %s — "
                    "running in offline mode",
                    exc,
                )
        else:
            logger.info(
                "MISTRAL_API_KEY not set — LLMClient in offline mode"
            )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """Return True when LLM inference is available."""
        return self._client is not None

    @property
    def model_version(self) -> str:
        """Return a model-version tag for audit/lineage columns."""
        if self.is_available:
            return f"llm:{self._model}"
        return "fallback:v0.1"

    # ── Chat completion ──────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        *,
        delay: float = _DEFAULT_CALL_DELAY,
    ) -> Optional[str]:
        """Send a single-turn chat prompt and return the assistant response.

        Args:
            prompt: The user-role message content.
            delay: Seconds to sleep *after* the call to pace rate limits.

        Returns:
            The stripped response text, or ``None`` if the client is
            unavailable or the call fails.
        """
        if not self.is_available:
            return None

        try:
            response = self._client.chat.complete(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content.strip()
            if delay > 0:
                time.sleep(delay)
            return text
        except Exception as exc:
            logger.error("LLM chat call failed: %s", exc)
            return None

    # ── JSON completion ──────────────────────────────────────────────────

    def chat_json(
        self,
        prompt: str,
        *,
        delay: float = _DEFAULT_CALL_DELAY,
    ) -> Optional[dict]:
        """Send a chat prompt and parse the response as JSON.

        Strips markdown code-fence wrappers (```json ... ```) before
        parsing.

        Args:
            prompt: The user-role message content.
            delay: Seconds to sleep after the call.

        Returns:
            A parsed dict, or ``None`` on failure.
        """
        raw = self.chat(prompt, delay=delay)
        if raw is None:
            return None
        try:
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Failed to parse LLM response as JSON: %s — raw=%s",
                exc,
                raw[:200],
            )
            return None
