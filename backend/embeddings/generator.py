"""
backend/embeddings/generator.py
Vector Embedding Generator. Calls the Mistral embedding API to produce
dense vector representations of interaction text for Qdrant storage and
similarity search.

When MISTRAL_API_KEY is not set, embedding generation is skipped
(returns None) so the rest of the pipeline can continue without it.
"""

from __future__ import annotations

from typing import Optional

from backend.core.config import get_settings
from backend.core.logging import setup_logger

logger = setup_logger(__name__)

# Mistral's embedding model and its output dimension.
_EMBEDDING_MODEL = "mistral-embed"
_EMBEDDING_DIMENSION = 1024


class EmbeddingGenerator:
    """Generate dense vector embeddings from text using Mistral-embed.

    Thread-safe and reusable — instantiate once and call
    :meth:`generate` for each piece of text.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key: Optional[str] = settings.MISTRAL_API_KEY
        self._client = None

        if self._api_key:
            try:
                from mistralai import Mistral

                self._client = Mistral(api_key=self._api_key)
                logger.info(
                    "EmbeddingGenerator initialised with model=%s",
                    _EMBEDDING_MODEL,
                )
            except ImportError:
                logger.warning(
                    "mistralai package not installed — embedding "
                    "generation disabled"
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialise embedding client: %s", exc
                )
        else:
            logger.info(
                "MISTRAL_API_KEY not set — embedding generation disabled"
            )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """Return True when embedding generation is available."""
        return self._client is not None

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        return _EMBEDDING_DIMENSION

    # ── Generation ───────────────────────────────────────────────────────

    def generate(self, text: str) -> Optional[list[float]]:
        """Generate a vector embedding for the given text.

        Args:
            text: The text to embed.  Should be a concise representation
                of the interaction (e.g. query_summary + response_summary).

        Returns:
            A list of floats (the embedding vector), or ``None`` if
            generation is unavailable or fails.
        """
        if not self.is_available:
            return None

        if not text or not text.strip():
            logger.warning("Empty text provided for embedding generation")
            return None

        try:
            response = self._client.embeddings.create(
                model=_EMBEDDING_MODEL,
                inputs=[text],
            )
            vector = response.data[0].embedding
            logger.debug(
                "Generated embedding: dim=%d text_len=%d",
                len(vector),
                len(text),
            )
            return vector
        except Exception as exc:
            logger.error("Embedding generation failed: %s", exc)
            return None

    def generate_batch(
        self, texts: list[str]
    ) -> list[Optional[list[float]]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: A list of texts to embed.

        Returns:
            A list of embedding vectors (or ``None`` for failures),
            in the same order as the input texts.
        """
        if not self.is_available:
            return [None] * len(texts)

        # Filter out empty texts but preserve positions
        results: list[Optional[list[float]]] = [None] * len(texts)
        valid_indices: list[int] = []
        valid_texts: list[str] = []

        for i, text in enumerate(texts):
            if text and text.strip():
                valid_indices.append(i)
                valid_texts.append(text)

        if not valid_texts:
            return results

        try:
            response = self._client.embeddings.create(
                model=_EMBEDDING_MODEL,
                inputs=valid_texts,
            )
            for idx, embedding_data in zip(
                valid_indices, response.data
            ):
                results[idx] = embedding_data.embedding

            logger.info(
                "Generated %d/%d embeddings in batch",
                sum(1 for r in results if r is not None),
                len(texts),
            )
            return results
        except Exception as exc:
            logger.error("Batch embedding generation failed: %s", exc)
            return results
