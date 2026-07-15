"""
services/enrichment_orchestrator.py
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
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from core.logging import setup_logger
from repositories.interaction_repository import InteractionRepository
from intelligence.llm_client import LLMClient
from intelligence.summarizer import SummarizationEngine
from intelligence.sentiment import SentimentEngine
from intelligence.risk_scorer import compute as compute_escalation_risk
from intelligence.root_cause import RootCauseEngine
from embeddings.generator import EmbeddingGenerator
from services.qdrant_service import QdrantService
from services.embedding_client import EmbeddingClient
from utils.date_helpers import ensure_utc

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

            # Step 2: Fetch raw ticket and AI analysis source text for complete issue chain
            main_ticket_query = text("""
                SELECT id, title, description, customer_name, created_by, resolution, status, created_at, updated_at, assigned_to
                FROM tickets
                WHERE id = :ticket_id
                LIMIT 1
            """)
            main_ticket = self.db.execute(main_ticket_query, {"ticket_id": record.ticket_id}).mappings().first()

            if main_ticket is None:
                logger.error(
                    "Enrichment aborted — ticket source record not found "
                    "in tickets table for ticket_id=%s",
                    record.ticket_id,
                )
                return False

            # Query all related sub-tickets
            sub_tickets_query = text("""
                SELECT id, title, description, resolution, status, created_at, updated_at, assigned_to, created_by
                FROM sub_tickets
                WHERE ticket_id = :ticket_id
                ORDER BY created_at ASC
            """)
            sub_tickets = self.db.execute(sub_tickets_query, {"ticket_id": record.ticket_id}).mappings().all()

            # Query main ticket AI analysis
            main_ai_query = text("""
                SELECT id, runbook_resolution, rag_resolution, decision_reason, confidence_score, source_used
                FROM ai_analysis
                WHERE ticket_id = :ticket_id
                LIMIT 1
            """)
            main_ai = self.db.execute(main_ai_query, {"ticket_id": record.ticket_id}).mappings().first()

            # Query sub-tickets AI analysis
            sub_ticket_ids = [st["id"] for st in sub_tickets]
            sub_ais = []
            if sub_ticket_ids:
                sub_ais_query = text("""
                    SELECT sub_ticket_id, runbook_resolution, rag_resolution, decision_reason, confidence_score, source_used
                    FROM sub_ticket_ai_analysis
                    WHERE sub_ticket_id IN :ids
                """).bindparams(bindparam("ids", expanding=True))
                sub_ais = self.db.execute(sub_ais_query, {"ids": list(sub_ticket_ids)}).mappings().all()

            # Query comments for main ticket
            main_comments_query = text("""
                SELECT comment_text, commented_by, created_at
                FROM comments
                WHERE ticket_id = :ticket_id
                ORDER BY created_at ASC
            """)
            main_comments = self.db.execute(main_comments_query, {"ticket_id": record.ticket_id}).mappings().all()

            # Query comments for sub-tickets
            sub_comments = []
            if sub_ticket_ids:
                sub_comments_query = text("""
                    SELECT comment_text, commented_by, created_at
                    FROM sub_ticket_comments
                    WHERE sub_ticket_id IN :ids
                    ORDER BY created_at ASC
                """).bindparams(bindparam("ids", expanding=True))
                sub_comments = self.db.execute(sub_comments_query, {"ids": list(sub_ticket_ids)}).mappings().all()

            # Resolve user classifications from user IDs involved
            comment_author_strs = {c["commented_by"] for c in main_comments if c["commented_by"]} | \
                                  {sc["commented_by"] for sc in sub_comments if sc["commented_by"]}
            
            comment_author_uuids = []
            for author_str in comment_author_strs:
                try:
                    comment_author_uuids.append(uuid.UUID(author_str))
                except ValueError:
                    pass

            user_uuids = set(comment_author_uuids)
            if main_ticket["created_by"]:
                user_uuids.add(main_ticket["created_by"])
            if main_ticket["assigned_to"]:
                user_uuids.add(main_ticket["assigned_to"])
            for st in sub_tickets:
                if st["created_by"]:
                    user_uuids.add(st["created_by"])
                if st["assigned_to"]:
                    user_uuids.add(st["assigned_to"])

            user_type_map = {}
            if user_uuids:
                users_query = text("""
                    SELECT id, user_type, role, name
                    FROM users
                    WHERE id IN :ids
                """).bindparams(bindparam("ids", expanding=True))
                users_rows = self.db.execute(users_query, {"ids": list(user_uuids)}).mappings().all()
                user_type_map = {row["id"]: row for row in users_rows}

            # Function to classify author
            def classify_author(author_str: str | None) -> str:
                if not author_str:
                    return "UNKNOWN"
                try:
                    author_uuid = uuid.UUID(author_str)
                    user_row = user_type_map.get(author_uuid)
                    if user_row:
                        u_type = user_row["user_type"]
                        if u_type == "CUSTOMER":
                            return "CUSTOMER"
                        elif u_type == "STAFF":
                            return "AGENT"
                    return "UNKNOWN"
                except ValueError:
                    return "UNKNOWN"

            # Dynamic repeat count calculation from actual data
            repeat_count = len(sub_tickets)

            # Trace logs of the issue chain context for complete visibility
            issue_chain_trace = {
                "main_ticket": {
                    "id": main_ticket["id"],
                    "title": main_ticket["title"],
                    "description": main_ticket["description"],
                    "resolution": main_ticket["resolution"],
                    "status": main_ticket["status"],
                    "created_by": main_ticket["created_by"],
                    "assigned_to": main_ticket["assigned_to"],
                },
                "sub_tickets": [
                    {
                        "id": st["id"],
                        "title": st["title"],
                        "description": st["description"],
                        "resolution": st["resolution"],
                        "status": st["status"],
                        "created_by": st["created_by"],
                        "assigned_to": st["assigned_to"],
                    } for st in sub_tickets
                ],
                "all_comments": []
            }

            customer_comment_texts = []
            agent_comment_texts = []

            for c in main_comments:
                author_class = classify_author(c["commented_by"])
                issue_chain_trace["all_comments"].append({
                    "text": c["comment_text"],
                    "author": c["commented_by"],
                    "category": author_class,
                    "created_at": str(c["created_at"]),
                    "source": "main_ticket"
                })
                if author_class == "CUSTOMER":
                    customer_comment_texts.append(c["comment_text"])
                elif author_class == "AGENT":
                    agent_comment_texts.append(c["comment_text"])

            for sc in sub_comments:
                author_class = classify_author(sc["commented_by"])
                issue_chain_trace["all_comments"].append({
                    "text": sc["comment_text"],
                    "author": sc["commented_by"],
                    "category": author_class,
                    "created_at": str(sc["created_at"]),
                    "source": "sub_ticket"
                })
                if author_class == "CUSTOMER":
                    customer_comment_texts.append(sc["comment_text"])
                elif author_class == "AGENT":
                    agent_comment_texts.append(sc["comment_text"])

            logger.info("Retrieved issue-chain context trace for ticket_id=%s: %s", record.ticket_id, issue_chain_trace)

            # Resolve customer_id if not present in captured event
            customer_id = record.customer_id
            if customer_id is None:
                customer_id = main_ticket["created_by"]
                if customer_id is None and main_ticket["customer_name"]:
                    logger.info(
                        "Resolving customer_id via customer_profiles for company_name=%s",
                        main_ticket["customer_name"],
                    )
                    profile_query = text("""
                        SELECT user_id FROM customer_profiles
                        WHERE LOWER(TRIM(company_name)) = :company_name
                        LIMIT 1
                    """)
                    profile_row = self.db.execute(
                        profile_query,
                        {"company_name": main_ticket["customer_name"].strip().lower()},
                    ).fetchone()
                    if profile_row:
                        customer_id = profile_row[0]
                        logger.info("Resolved customer_id=%s", customer_id)

            # Customer's text representation
            customer_components = [main_ticket["title"], main_ticket["description"]]
            for st in sub_tickets:
                customer_components.extend([st["title"], st["description"]])
            customer_components.extend(customer_comment_texts)
            customer_text = " ".join(filter(None, customer_components))

            # Resolution text hierarchy
            agent_components = []
            if main_ticket["resolution"]:
                agent_components.append(main_ticket["resolution"])
            for st in sub_tickets:
                if st["resolution"]:
                    agent_components.append(st["resolution"])

            if main_ai:
                for r in [main_ai["runbook_resolution"], main_ai["rag_resolution"], main_ai["decision_reason"]]:
                    if r and r.strip():
                        agent_components.append(r)

            for sa in sub_ais:
                for r in [sa["runbook_resolution"], sa["rag_resolution"], sa["decision_reason"]]:
                    if r and r.strip():
                        agent_components.append(r)

            agent_components.extend(agent_comment_texts)
            resolution_text = " ".join(filter(None, agent_components))

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
            
            # Fetch risk scorer integration signals
            risk_signals = {
                "escalation_source": main_ai["source_used"] if main_ai else None,
                "recommendation_source": None,
                "approval_action": None,
                "ai_confidences": [],
                "ticket_status": main_ticket["status"],
                "latest_activity_at": None,
            }

            if main_ai and main_ai["confidence_score"] is not None:
                risk_signals["ai_confidences"].append(float(main_ai["confidence_score"]))
            for sa in sub_ais:
                if sa["confidence_score"] is not None:
                    risk_signals["ai_confidences"].append(float(sa["confidence_score"]))

            # Bypassed: recommendations table does not exist in production.
            # recommendation_source defaults to None; risk scorer uses its fallback.

            # Wrap approval_history query in nested savepoint to prevent
            # a table-not-found error from aborting the outer transaction.
            try:
                with self.db.begin_nested():
                    approval_row = self.db.execute(
                        text("""
                            SELECT action
                            FROM approval_history
                            WHERE ticket_id = :ticket_id
                            ORDER BY created_at DESC NULLS LAST
                            LIMIT 1
                        """),
                        {"ticket_id": record.ticket_id},
                    ).mappings().first()
                    if approval_row:
                        risk_signals["approval_action"] = approval_row["action"]
            except Exception:
                logger.warning("Unable to load approval history for ticket_id=%s", record.ticket_id)

            # Calculate latest_activity_at — normalise all datetimes to UTC
            timestamps = []
            if main_ticket["updated_at"]:
                timestamps.append(ensure_utc(main_ticket["updated_at"]))
            elif main_ticket["created_at"]:
                timestamps.append(ensure_utc(main_ticket["created_at"]))
            
            for st in sub_tickets:
                if st["updated_at"]:
                    timestamps.append(ensure_utc(st["updated_at"]))
                elif st["created_at"]:
                    timestamps.append(ensure_utc(st["created_at"]))

            for c in main_comments:
                if c["created_at"]:
                    timestamps.append(ensure_utc(c["created_at"]))

            for sc in sub_comments:
                if sc["created_at"]:
                    timestamps.append(ensure_utc(sc["created_at"]))

            try:
                with self.db.begin_nested():
                    approval_rows = self.db.execute(
                        text("SELECT created_at FROM approval_history WHERE ticket_id = :ticket_id"),
                        {"ticket_id": record.ticket_id}
                    ).mappings().all()
                    for ar in approval_rows:
                        if ar["created_at"]:
                            timestamps.append(ensure_utc(ar["created_at"]))
            except Exception:
                pass

            if timestamps:
                valid_timestamps = [ts for ts in timestamps if ts is not None]
                if valid_timestamps:
                    risk_signals["latest_activity_at"] = max(valid_timestamps)

            ticket_history = self.repository.get_ticket_history(record.ticket_id)
            risk_result = compute_escalation_risk(
                ticket_history,
                escalation_source=risk_signals["escalation_source"],
                recommendation_source=risk_signals["recommendation_source"],
                approval_action=risk_signals["approval_action"],
                ai_confidences=risk_signals["ai_confidences"],
                ticket_status=risk_signals["ticket_status"],
                latest_activity_at=risk_signals["latest_activity_at"],
            )
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
                "resolution_state": main_ticket["status"],
                "ai_analysis_id": main_ai["id"] if (main_ai and record.ai_analysis_id is None) else record.ai_analysis_id,
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
                "repeat_count": repeat_count,
                "qdrant_vector_id": qdrant_vector_id,
                "model_version": self.llm.model_version,
            }

            logger.info("Updating OperationalAnalysis record fields in PostgreSQL")
            self.repository.update(operational_analysis_id, update_data)

            logger.info("Saving OperationalAnalysis...")
            self.db.flush()
            logger.info("OperationalAnalysis saved successfully.")

            # Automatically run rollup regeneration and commit
            from services.aggregation_service import AggregationService
            aggregation_service = AggregationService(self.db)
            aggregation_service.generate_all_rollups()
            self.db.commit()
            logger.info("Transaction committed successfully.")
            logger.info(
                "Enrichment successfully persisted for operational_analysis_id=%s",
                operational_analysis_id,
            )

            # Step 9: Trigger Downstream Customer Clustering & Health Evaluation
            # Core enrichment is already committed above. Downstream failures must
            # not roll back the persisted enrichment results.
            if customer_id:
                # --- Clustering stage ---
                try:
                    logger.info(
                        "Triggering downstream clustering for customer_id=%s",
                        customer_id,
                    )
                    from services.customer_clustering_service import (
                        CustomerClusteringService,
                    )

                    clustering_service = CustomerClusteringService(self.db)
                    clustering_service.group_customer_issues(customer_id)
                    self.db.commit()
                    logger.info(
                        "Clustering completed and committed for customer_id=%s",
                        customer_id,
                    )
                except Exception:
                    self.db.rollback()
                    logger.exception(
                        "Clustering failed for customer_id=%s. "
                        "Core enrichment remains committed.",
                        customer_id,
                    )

                # --- Customer health stage ---
                try:
                    logger.info(
                        "Triggering customer health evaluation for customer_id=%s",
                        customer_id,
                    )
                    from services.customer_health_service import (
                        CustomerHealthService,
                    )

                    health_service = CustomerHealthService(self.db)
                    health_service.evaluate_customer_health(customer_id)
                    self.db.commit()
                    logger.info(
                        "Customer health evaluation completed and committed for customer_id=%s",
                        customer_id,
                    )
                except Exception:
                    self.db.rollback()
                    logger.exception(
                        "Customer health evaluation failed for customer_id=%s. "
                        "Core enrichment remains committed.",
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
