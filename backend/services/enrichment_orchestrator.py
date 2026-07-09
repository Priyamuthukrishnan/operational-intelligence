"""
backend/services/enrichment_orchestrator.py
Enrichment Orchestrator. Coordinates the complete enrichment flow for a
single OperationalAnalysis record:
  1. Retrieve raw text data from tickets/ai_analysis.
  2. Generate query and response summaries.
  3. Analyze emotional tone (sentiment).
  4. Predict root cause and confidence.
  5. Compute escalation risk score and band.
  6. Generate vector embeddings and upsert to Qdrant.
  7. Persist enriched metadata back to PostgreSQL via repository/ORM.
  8. Auto-trigger customer clustering.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.logging import setup_logger
from backend.repositories.interaction_repository import InteractionRepository
from backend.intelligence.llm_client import LLMClient
from backend.intelligence.summarizer import SummarizationEngine
from backend.intelligence.sentiment import SentimentEngine
from backend.intelligence.risk_scorer import compute as compute_escalation_risk
from backend.intelligence.root_cause import RootCauseEngine
from backend.embeddings.generator import EmbeddingGenerator
from backend.services.qdrant_service import QdrantService
from backend.services.embedding_client import EmbeddingClient

logger = setup_logger(__name__)


class EnrichmentOrchestrator:
    """Orchestrates metadata enrichment and vector database persistence
    for captured interaction events.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = InteractionRepository(db)

        # ── Initialize Intelligence Modules ─────────────────────────────
        self.llm = LLMClient()
        self.summarizer = SummarizationEngine(self.llm)
        self.sentiment_engine = SentimentEngine(self.llm)
        self.root_cause_engine = RootCauseEngine(self.llm)
        self.embedding_generator = EmbeddingGenerator()

        # ── Initialize Qdrant Service ──────────────────────────────────
        self.qdrant: Optional[QdrantService] = None
        try:
            self.qdrant = QdrantService()
            logger.info("Qdrant service successfully initialized for enrichment")
        except Exception as exc:
            logger.warning(
                "Qdrant service unavailable for enrichment. "
                "Vector generation will be skipped: %s",
                exc,
            )

        # ── Initialize External Embedding Service Client ─────────────────
        self.embedding_client: Optional[EmbeddingClient] = None
        try:
            self.embedding_client = EmbeddingClient()
            if not self.embedding_client.is_available:
                logger.warning(
                    "External embedding client initialised but unavailable"
                )
                self.embedding_client = None
            else:
                logger.info("External embedding client successfully initialized")
        except Exception as exc:
            logger.warning(
                "External embedding client init failed. "
                "External embedding ingestion will be skipped: %s",
                exc,
            )

    def enrich_interaction(self, operational_analysis_id: uuid.UUID) -> bool:
        """Enrich a single interaction record.

        Reads the OperationalAnalysis record, queries source tables for raw
        text, runs analysis modules, updates the database, and triggers
        clustering.

        Args:
            operational_analysis_id: UUID of the operational_analysis record.

        Returns:
            True if enrichment completed successfully, False otherwise.
        """
        logger.info(
            "Starting enrichment pipeline for operational_analysis_id=%s",
            operational_analysis_id,
        )

        try:
            # Step 1: Fetch OperationalAnalysis record
            record = self.repository.get_by_id(operational_analysis_id)
            if record is None:
                logger.error(
                    "Enrichment aborted — operational_analysis record not found "
                    "for id=%s",
                    operational_analysis_id,
                )
                return False

            logger.info(
                "Retrieved operational record: ticket_id=%s customer_id=%s",
                record.ticket_id,
                record.customer_id,
            )

            # Step 2: Fetch raw ticket and AI analysis source text
            source_query = text("""
                SELECT
                    t.title,
                    t.description,
                    t.customer_name,
                    t.created_by,
                    t.resolution,
                    a.runbook_resolution,
                    a.rag_resolution,
                    a.decision_reason
                FROM tickets t
                LEFT JOIN ai_analysis a ON a.ticket_id = t.id
                WHERE t.id = :ticket_id
                LIMIT 1
            """)
            source_row = self.db.execute(
                source_query, {"ticket_id": record.ticket_id}
            ).fetchone()

            if source_row is None:
                logger.error(
                    "Enrichment aborted — ticket source record not found "
                    "in tickets table for ticket_id=%s",
                    record.ticket_id,
                )
                return False

            title, description, customer_name, created_by, t_res, r_res, rag_res, dec_reason = source_row
            logger.info("Retrieved source ticket and AI analysis columns successfully")

            # Resolve customer_id if not present in captured event
            customer_id = record.customer_id
            if customer_id is None:
                customer_id = created_by
                if customer_id is None and customer_name:
                    logger.info(
                        "Resolving customer_id via customer_profiles for company_name=%s",
                        customer_name,
                    )
                    profile_query = text("""
                        SELECT user_id FROM customer_profiles
                        WHERE LOWER(TRIM(company_name)) = :company_name
                        LIMIT 1
                    """)
                    profile_row = self.db.execute(
                        profile_query,
                        {"company_name": customer_name.strip().lower()},
                    ).fetchone()
                    if profile_row:
                        customer_id = profile_row[0]
                        logger.info("Resolved customer_id=%s", customer_id)

            # Customer's text representation
            customer_text = " ".join(filter(None, [title, description]))

            # Resolution text resolution hierarchy
            resolution_text = t_res
            if not resolution_text or not resolution_text.strip():
                # Fallbacks from AI analysis
                resolution_text = next(
                    (r for r in (r_res, rag_res, dec_reason) if r and r.strip()),
                    None,
                )

            # Step 3: Run Summarization Engine
            logger.info("Generating query and response summaries")
            query_summary = self.summarizer.summarize_query(customer_text)
            response_summary = self.summarizer.summarize_resolution(resolution_text)

            # Step 4: Run Sentiment Engine
            logger.info("Analyzing emotional tone and sentiment score")
            sentiment_label, sentiment_score = self.sentiment_engine.analyze(
                customer_text
            )

            # Step 5: Run Root Cause Engine
            logger.info("Predicting root cause category")
            rc_cat, rc_conf = self.root_cause_engine.analyze(
                query_summary or customer_text
            )

            # Step 6: Run Escalation Risk Scorer
            logger.info("Calculating escalation risk and classification band")
            ticket_history = self.repository.get_ticket_history(record.ticket_id)
            risk_result = compute_escalation_risk(ticket_history)
            risk_score = risk_result["escalation_risk_score"]
            risk_band = risk_result["escalation_risk_band"]
            confidence_decay_score = risk_result["confidence_decay_score"]
            momentum_score = risk_result["momentum_score"]
            risk_multiplier = risk_result["risk_multiplier"]
            risk_reason = risk_result["risk_reason"]
            risk_processed = risk_result["risk_processed"]

            # Step 7: Generate Embedding and Upsert to Qdrant
            qdrant_vector_id = None
            if self.embedding_generator.is_available and self.qdrant is not None:
                embedding_text = " ".join(
                    filter(None, [query_summary, response_summary])
                )
                if not embedding_text:
                    embedding_text = customer_text

                logger.info(
                    "Generating embedding vector for operational_analysis_id=%s",
                    operational_analysis_id,
                )
                vector = self.embedding_generator.generate(embedding_text)

                if vector:
                    payload = {
                        "ticket_id": str(record.ticket_id),
                        "customer_id": str(customer_id) if customer_id else None,
                        "query_summary": query_summary,
                        "response_summary": response_summary,
                    }
                    logger.info(
                        "Upserting vector to Qdrant for operational_analysis_id=%s",
                        operational_analysis_id,
                    )
                    upsert_ok = self.qdrant.upsert_vector(
                        point_id=str(operational_analysis_id),
                        vector=vector,
                        payload=payload,
                    )
                    if upsert_ok:
                        qdrant_vector_id = str(operational_analysis_id)
                else:
                    logger.warning("Embedding generation returned None")

            # Step 7b: Send enriched data to external embedding service
            if self.embedding_client is not None:
                try:
                    logger.info(
                        "Sending enriched data to external embedding service "
                        "for operational_analysis_id=%s",
                        operational_analysis_id,
                    )
                    ext_vector_id = self.embedding_client.ingest(
                        operational_analysis_id=operational_analysis_id,
                        ticket_id=record.ticket_id,
                        customer_id=customer_id,
                        query_summary=query_summary,
                        response_summary=response_summary,
                        sentiment_label=sentiment_label,
                        sentiment_score=sentiment_score,
                        root_cause_category=rc_cat,
                        root_cause_confidence=rc_conf,
                        escalation_risk_score=risk_score,
                        escalation_risk_band=risk_band,
                        captured_at=record.captured_at.isoformat() if getattr(record, "captured_at", None) else None,
                    )
                    if ext_vector_id and qdrant_vector_id is None:
                        qdrant_vector_id = ext_vector_id
                        logger.info(
                            "Using external embedding service vector_id=%s "
                            "as qdrant_vector_id",
                            ext_vector_id,
                        )
                except Exception as emb_exc:
                    logger.warning(
                        "External embedding service ingestion failed for "
                        "operational_analysis_id=%s: %s. Continuing enrichment.",
                        operational_analysis_id,
                        emb_exc,
                    )

            # Step 8: Update PostgreSQL record via repository
            update_data = {
                "customer_id": customer_id,
                "query_summary": query_summary,
                "response_summary": response_summary,
                "sentiment_label": sentiment_label,
                "sentiment_score": sentiment_score,
                "root_cause_category": rc_cat,
                "root_cause_confidence": rc_conf,
                "escalation_risk_score": risk_score,
                "escalation_risk_band": risk_band,
                "confidence_decay_score": confidence_decay_score,
                "momentum_score": momentum_score,
                "risk_multiplier": risk_multiplier,
                "risk_reason": risk_reason,
                "risk_processed": risk_processed,
                "qdrant_vector_id": qdrant_vector_id,
                "model_version": self.llm.model_version,
            }

            logger.info("Updating OperationalAnalysis record fields in PostgreSQL")
            self.repository.update(operational_analysis_id, update_data)

            # Commit the enrichment changes
            self.db.commit()
            logger.info(
                "Enrichment successfully persisted for operational_analysis_id=%s",
                operational_analysis_id,
            )

            # Step 9: Trigger Downstream Customer Clustering & Health Evaluation
            if customer_id:
                try:
                    logger.info(
                        "Triggering downstream clustering for customer_id=%s",
                        customer_id,
                    )
                    from backend.services.customer_clustering_service import (
                        CustomerClusteringService,
                    )

                    clustering_service = CustomerClusteringService(self.db)
                    clustering_service.group_customer_issues(customer_id)
                    logger.info(
                        "Clustering completed successfully for customer_id=%s",
                        customer_id,
                    )

                    logger.info(
                        "Triggering customer health evaluation for customer_id=%s",
                        customer_id,
                    )
                    from backend.services.customer_health_service import (
                        CustomerHealthService,
                    )

                    health_service = CustomerHealthService(self.db)
                    health_service.evaluate_customer_health(customer_id)
                    logger.info(
                        "Customer health evaluation completed for customer_id=%s",
                        customer_id,
                    )
                except Exception as downstream_exc:
                    logger.exception(
                        "Downstream pipeline triggers failed for customer_id=%s. "
                        "Continuing as enrichment transaction is already committed.",
                        customer_id,
                    )
            else:
                logger.warning(
                    "Skipped customer clustering and health: customer_id is unresolved"
                )


            return True

        except Exception as exc:
            self.db.rollback()
            logger.exception(
                "Enrichment pipeline failed for operational_analysis_id=%s. "
                "Rolled back transaction.",
                operational_analysis_id,
            )
            return False
