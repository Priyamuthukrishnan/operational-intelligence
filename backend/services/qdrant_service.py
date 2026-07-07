"""
backend/services/qdrant_service.py
Qdrant Vector Database Service.

Provides vector retrieval, similarity search, and upsert operations
against a Qdrant collection.  All configuration is loaded from
environment variables via Settings — no hardcoded collection names,
thresholds, or point IDs.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Optional

from backend.core.config import get_settings
from backend.core.logging import setup_logger

logger = setup_logger(__name__)


# ── Domain Exceptions ────────────────────────────────────────────────────


class QdrantConfigError(Exception):
    """Raised when required Qdrant configuration is missing."""


class QdrantConnectionError(Exception):
    """Raised when the Qdrant server is unreachable."""


class QdrantCollectionError(Exception):
    """Raised when the configured collection does not exist."""


# ── Service ──────────────────────────────────────────────────────────────


class QdrantService:
    """Read-only wrapper around the Qdrant vector database.

    Responsibilities:
    1. Validate that all required Qdrant configuration is present.
    2. Establish a connection to the Qdrant cluster.
    3. Retrieve individual or batched vectors by point ID.
    4. Execute nearest-neighbour similarity searches.

    All methods are **read-only** — no data is written to Qdrant.
    """

    def __init__(self) -> None:
        """Initialise the Qdrant client from environment-sourced settings.

        Raises:
            QdrantConfigError: If ``QDRANT_URL``, ``QDRANT_API_KEY``, or
                ``QDRANT_COLLECTION_NAME`` is not set in the environment.
            QdrantConnectionError: If the Qdrant server is unreachable.
        """
        settings = get_settings()

        # ── Validate required configuration ──────────────────────────────
        missing: list[str] = []
        if not settings.QDRANT_URL:
            missing.append("QDRANT_URL")
        if not settings.QDRANT_API_KEY:
            missing.append("QDRANT_API_KEY")
        if not settings.QDRANT_COLLECTION_NAME:
            missing.append("QDRANT_COLLECTION_NAME")

        if missing:
            msg = (
                "Missing required Qdrant configuration: "
                f"{', '.join(missing)}. "
                "Please set these values in your .env file."
            )
            logger.error(msg)
            raise QdrantConfigError(msg)

        self._collection_name: str = settings.QDRANT_COLLECTION_NAME

        # ── Initialise client ────────────────────────────────────────────
        try:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
                timeout=30,
            )
            logger.info(
                "Qdrant client initialised: url=%s collection=%s",
                settings.QDRANT_URL,
                self._collection_name,
            )
        except Exception as exc:
            msg = f"Failed to initialise Qdrant client: {exc}"
            logger.error(msg)
            raise QdrantConnectionError(msg) from exc

    # ── Point ID Handling ────────────────────────────────────────────────

    @staticmethod
    def _coerce_point_id(raw: str) -> str | int:
        """Convert a raw point-ID string to the appropriate type.

        Qdrant supports both UUID-string and integer point IDs.  This
        method inspects the value at runtime and returns the correct type
        without hardcoding any assumption.

        Args:
            raw: The point ID as stored in ``operational_analysis.qdrant_vector_id``.

        Returns:
            The ID as a ``str`` (if it looks like a UUID) or ``int``
            (if it is purely numeric), otherwise the original ``str``.
        """
        # Try UUID first
        try:
            _uuid.UUID(raw)
            return raw  # Valid UUID → keep as string
        except (ValueError, AttributeError):
            pass

        # Try integer
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass

        # Fallback: return as-is
        return raw

    # ── Single Vector Retrieval ──────────────────────────────────────────

    def get_vector(
        self, vector_id: str
    ) -> Optional[dict[str, Any]]:
        """Retrieve a single point from Qdrant by its ID.

        Args:
            vector_id: The raw point ID string (coerced at runtime).

        Returns:
            A dict ``{"id": ..., "vector": [...], "payload": {...}}``
            or ``None`` if the point does not exist.
        """
        coerced_id = self._coerce_point_id(vector_id)

        try:
            from qdrant_client.models import PointIdsList

            results = self._client.retrieve(
                collection_name=self._collection_name,
                ids=[coerced_id],
                with_vectors=True,
                with_payload=True,
            )

            if not results:
                logger.warning(
                    "Vector not found in Qdrant: vector_id=%s (coerced=%s)",
                    vector_id,
                    coerced_id,
                )
                return None

            point = results[0]
            return {
                "id": str(point.id),
                "vector": point.vector,
                "payload": point.payload or {},
            }

        except Exception as exc:
            logger.error(
                "Failed to retrieve vector from Qdrant: "
                "vector_id=%s error=%s",
                vector_id,
                exc,
            )
            return None

    # ── Batch Vector Retrieval ───────────────────────────────────────────

    def get_vectors(
        self, vector_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Batch-retrieve multiple points from Qdrant.

        Missing IDs are skipped gracefully with a warning log.

        Args:
            vector_ids: List of raw point ID strings.

        Returns:
            A list of dicts, each with ``{"id", "vector", "payload"}``.
            Only successfully retrieved points are included.
        """
        if not vector_ids:
            return []

        coerced_ids = [self._coerce_point_id(vid) for vid in vector_ids]

        try:
            results = self._client.retrieve(
                collection_name=self._collection_name,
                ids=coerced_ids,
                with_vectors=True,
                with_payload=True,
            )

            retrieved = []
            for point in results:
                retrieved.append(
                    {
                        "id": str(point.id),
                        "vector": point.vector,
                        "payload": point.payload or {},
                    }
                )

            if len(retrieved) < len(vector_ids):
                logger.warning(
                    "Qdrant batch retrieval: requested=%d retrieved=%d "
                    "(some vectors missing)",
                    len(vector_ids),
                    len(retrieved),
                )

            logger.info(
                "Batch retrieved %d/%d vectors from Qdrant",
                len(retrieved),
                len(vector_ids),
            )
            return retrieved

        except Exception as exc:
            logger.error(
                "Failed to batch-retrieve vectors from Qdrant: "
                "count=%d error=%s",
                len(vector_ids),
                exc,
            )
            return []

    # ── Similarity Search ────────────────────────────────────────────────

    def search_similar(
        self,
        vector: list[float],
        limit: int,
        score_threshold: float,
    ) -> list[dict[str, Any]]:
        """Run nearest-neighbour similarity search in Qdrant using query_points.

        Args:
            vector: The query vector to search against.
            limit: Maximum number of results to return.
            score_threshold: Minimum similarity score to include.

        Returns:
            A list of dicts ``[{"id": ..., "score": ..., "payload": {...}}, ...]``
            ordered by descending similarity score.
        """
        try:
            res = self._client.query_points(
                collection_name=self._collection_name,
                query=vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            matches = []
            for scored_point in res.points:
                matches.append(
                    {
                        "id": str(scored_point.id),
                        "score": scored_point.score,
                        "payload": scored_point.payload or {},
                    }
                )

            logger.info(
                "Qdrant similarity search returned %d result(s) "
                "(limit=%d threshold=%.3f)",
                len(matches),
                limit,
                score_threshold,
            )
            return matches

        except Exception as exc:
            logger.error(
                "Qdrant similarity search failed: error=%s", exc
            )
            return []

    # ── Vector Upsert ────────────────────────────────────────────────────

    def upsert_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Upsert a single vector point into the Qdrant collection.

        Creates a new point or overwrites an existing point with the
        same ``point_id``.

        Args:
            point_id: The unique identifier for this point (typically
                the OperationalAnalysis UUID).
            vector: The dense embedding vector.
            payload: Optional metadata dict attached to the point.

        Returns:
            ``True`` if the upsert succeeded, ``False`` otherwise.
        """
        coerced_id = self._coerce_point_id(point_id)

        try:
            from qdrant_client.models import PointStruct

            point = PointStruct(
                id=coerced_id,
                vector=vector,
                payload=payload or {},
            )
            self._client.upsert(
                collection_name=self._collection_name,
                points=[point],
            )
            logger.info(
                "Upserted vector to Qdrant: point_id=%s collection=%s",
                point_id,
                self._collection_name,
            )
            return True

        except Exception as exc:
            logger.error(
                "Failed to upsert vector to Qdrant: "
                "point_id=%s error=%s",
                point_id,
                exc,
            )
            return False

    def upsert_vectors(
        self,
        points: list[dict[str, Any]],
    ) -> int:
        """Batch-upsert multiple vector points.

        Args:
            points: A list of dicts, each containing::

                {
                    "id": str,           # point ID
                    "vector": list[float],
                    "payload": dict,     # optional
                }

        Returns:
            The count of successfully upserted points.
        """
        if not points:
            return 0

        try:
            from qdrant_client.models import PointStruct

            qdrant_points = [
                PointStruct(
                    id=self._coerce_point_id(p["id"]),
                    vector=p["vector"],
                    payload=p.get("payload", {}),
                )
                for p in points
            ]
            self._client.upsert(
                collection_name=self._collection_name,
                points=qdrant_points,
            )
            logger.info(
                "Batch-upserted %d vector(s) to Qdrant",
                len(qdrant_points),
            )
            return len(qdrant_points)

        except Exception as exc:
            logger.error(
                "Batch upsert to Qdrant failed: count=%d error=%s",
                len(points),
                exc,
            )
            return 0
