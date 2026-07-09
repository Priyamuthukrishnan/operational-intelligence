"""
backend/services/embedding_client.py
HTTP client for the external embedding service API.

The embedding service is maintained separately and exposes two endpoints:
  - POST /api/documents/ingest-json   → Ingest operational ticket analysis JSON.
  - POST /api/products/find           → Search for similar operational tickets.

This client does NOT generate embeddings locally — it delegates entirely to the
external service and returns vector IDs or search results as-is.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import httpx

from backend.core.config import get_settings
from backend.core.logging import setup_logger

logger = setup_logger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://127.0.0.1:8001"
_INGEST_PATH = "/api/documents/ingest-json"
_SEARCH_PATH = "/api/products/find"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 2


class EmbeddingClientError(Exception):
    """Raised when the embedding service returns an unexpected response."""


class EmbeddingClient:
    """Synchronous HTTP client for the external embedding service.

    Usage::

        client = EmbeddingClient()
        if client.is_available:
            result = client.ingest(payload)
            matches = client.search(query_text)

    The client gracefully degrades: if the embedding service URL is not
    configured or the service is unreachable, ``is_available`` returns
    ``False`` and operations return ``None`` / empty lists.
    """

    def __init__(self) -> None:
        settings = get_settings()

        self._base_url: str = getattr(
            settings, "EMBEDDING_SERVICE_URL", None
        ) or _DEFAULT_BASE_URL

        self._timeout = _DEFAULT_TIMEOUT_SECONDS
        self._client: Optional[httpx.Client] = None

        try:
            transport = httpx.HTTPTransport(retries=_MAX_RETRIES)
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                transport=transport,
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                "EmbeddingClient initialised: base_url=%s timeout=%.1fs",
                self._base_url,
                self._timeout,
            )
        except Exception as exc:
            logger.warning(
                "Failed to initialise EmbeddingClient: %s", exc
            )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """Return True when the HTTP client was initialised successfully."""
        return self._client is not None

    # ── Ingest ───────────────────────────────────────────────────────────

    def ingest(
        self,
        *,
        operational_analysis_id: uuid.UUID,
        ticket_id: uuid.UUID,
        customer_id: Optional[uuid.UUID],
        query_summary: Optional[str],
        response_summary: Optional[str],
        sentiment_label: Optional[str],
        sentiment_score: Optional[float],
        root_cause_category: Optional[str],
        root_cause_confidence: Optional[float],
        escalation_risk_score: Optional[float],
        escalation_risk_band: Optional[str],
        captured_at: Optional[str] = None,
    ) -> Optional[str]:
        """Send operational analysis data to the embedding service for ingestion.

        Posts the enriched ticket analysis JSON to the external embedding
        service's ``/api/documents/ingest-json`` endpoint.  The service
        generates embeddings, stores the vector, and returns a reference ID.

        Args:
            operational_analysis_id: Primary key of the operational_analysis record.
            ticket_id: Associated ticket UUID.
            customer_id: Resolved customer UUID (may be None).
            query_summary: Summarised customer query text.
            response_summary: Summarised resolution text.
            sentiment_label: Sentiment classification label.
            sentiment_score: Numeric sentiment score.
            root_cause_category: Predicted root cause category.
            root_cause_confidence: Root cause prediction confidence.
            escalation_risk_score: Computed risk score.
            escalation_risk_band: Risk classification band.
            captured_at: ISO timestamp of when the event was captured.

        Returns:
            The vector/document ID string returned by the embedding service,
            or ``None`` if ingestion failed.
        """
        if not self.is_available:
            logger.warning("EmbeddingClient unavailable — skipping ingest")
            return None

        payload: dict[str, Any] = {
            "project_id": "operational-intelligence",
            "project_key": "operational-intelligence",
            "namespace": "operational-intelligence",
            "metadata": {
                "tag": "operational_ticket_analysis",
                "type": "ticket"
            },
            "content": {
                "operational_analysis_id": str(operational_analysis_id),
                "ticket_id": str(ticket_id),
                "customer_id": str(customer_id) if customer_id else None,
                "query_summary": query_summary,
                "response_summary": response_summary,
                "sentiment_label": sentiment_label,
                "sentiment_score": sentiment_score,
                "root_cause_category": root_cause_category,
                "root_cause_confidence": root_cause_confidence,
                "escalation_risk_score": escalation_risk_score,
                "escalation_risk_band": escalation_risk_band,
                "captured_at": captured_at,
            }
        }

        logger.info(
            "Ingesting analysis into embedding service: "
            "operational_analysis_id=%s ticket_id=%s",
            operational_analysis_id,
            ticket_id,
        )

        try:
            response = self._client.post(_INGEST_PATH, json=payload)
            response.raise_for_status()

            data = response.json()
            vector_id = (
                data.get("vector_id")
                or data.get("document_id")
                or data.get("id")
            )

            if vector_id:
                logger.info(
                    "Embedding service ingestion succeeded: "
                    "vector_id=%s operational_analysis_id=%s",
                    vector_id,
                    operational_analysis_id,
                )
                return str(vector_id)

            # The service responded successfully but without a recognisable ID
            logger.warning(
                "Embedding service returned 2xx but no vector_id in "
                "response body: %s",
                data,
            )
            return None

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Embedding service ingest returned HTTP %d: %s "
                "(operational_analysis_id=%s)",
                exc.response.status_code,
                exc.response.text[:500],
                operational_analysis_id,
            )
            return None
        except httpx.RequestError as exc:
            logger.error(
                "Embedding service ingest request failed: %s "
                "(operational_analysis_id=%s)",
                exc,
                operational_analysis_id,
            )
            return None
        except Exception as exc:
            logger.error(
                "Unexpected error during embedding ingest: %s "
                "(operational_analysis_id=%s)",
                exc,
                operational_analysis_id,
            )
            return None

    # ── Search ───────────────────────────────────────────────────────────

    def search(
        self,
        query_text: str,
        *,
        limit: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Search the embedding service for similar operational tickets.

        Posts the query text to the external embedding service's
        ``/api/products/find`` endpoint and returns matching results.

        Args:
            query_text: The text to search against (e.g. a query summary
                or combined summary string).
            limit: Maximum number of results to return.
            filters: Optional filter criteria forwarded to the service.

        Returns:
            A list of match dicts from the embedding service response,
            or an empty list on failure.
        """
        if not self.is_available:
            logger.warning("EmbeddingClient unavailable — skipping search")
            return []

        if not query_text or not query_text.strip():
            logger.warning("Empty query_text provided for embedding search")
            return []

        payload: dict[str, Any] = {
            "query": query_text,
            "limit": limit,
        }
        if filters:
            payload["filters"] = filters

        logger.info(
            "Searching embedding service: query_len=%d limit=%d",
            len(query_text),
            limit,
        )

        try:
            response = self._client.post(_SEARCH_PATH, json=payload)
            response.raise_for_status()

            data = response.json()

            # Accept both a top-level list or a nested "results" key
            results: list[dict[str, Any]]
            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                results = data.get("results", data.get("matches", []))
            else:
                results = []

            logger.info(
                "Embedding service search returned %d result(s)",
                len(results),
            )
            return results

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Embedding service search returned HTTP %d: %s",
                exc.response.status_code,
                exc.response.text[:500],
            )
            return []
        except httpx.RequestError as exc:
            logger.error(
                "Embedding service search request failed: %s", exc
            )
            return []
        except Exception as exc:
            logger.error(
                "Unexpected error during embedding search: %s", exc
            )
            return []

    # ── Cleanup ──────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._client:
            self._client.close()
            logger.info("EmbeddingClient connection pool closed")
