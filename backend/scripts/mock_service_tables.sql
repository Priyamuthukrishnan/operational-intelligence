-- ============================================================================
--  MOCK SERVICE TABLES  (local dev only)
--  These stand in for the service team's tables that the operational layer
--  only READS. They use the same names/columns as the real ones, so agent
--  code does not change when you switch to the real service DB.
--
--  Your OWN tables (operational_analysis / interaction_analytics, issue_clusters,
--  root_cause_taxonomy) are created from the SQLAlchemy models in backend/models/
--  -- do NOT recreate them here. Run this file only to get readable input data.
--
--  Usage:  psql "$DATABASE_URL" -f backend/scripts/mock_service_tables.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id   BIGSERIAL PRIMARY KEY,
    company_name  TEXT,
    contact_name  TEXT,
    email         TEXT,
    phone         TEXT,
    health_score  NUMERIC(5,2),     -- operational layer writes this
    risk_band     TEXT              -- operational layer writes this
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id        BIGSERIAL PRIMARY KEY,
    customer_id      BIGINT REFERENCES customers(customer_id),
    title            TEXT,
    description      TEXT,
    category         TEXT,
    sub_category     TEXT,
    application_name TEXT,
    status           TEXT,
    priority         SMALLINT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comments (          -- *** main input: message text ***
    comment_id    BIGSERIAL PRIMARY KEY,
    ticket_id     BIGINT REFERENCES tickets(ticket_id),
    sub_ticket_id BIGINT,
    sender_type   TEXT,        -- customer | agent | ai | manager | system
    body          TEXT,        -- summarizer + sentiment read this
    is_internal   BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_analysis (       -- *** read-only resolution context ***
    id                  BIGSERIAL PRIMARY KEY,
    ticket_id           BIGINT REFERENCES tickets(ticket_id),
    category_prediction TEXT,
    similarity_score    NUMERIC(4,3),
    confidence_score    NUMERIC(4,3),
    source_used         TEXT,     -- rag | runbook | human
    decision_reason     TEXT,
    runbook_score       NUMERIC(4,3),
    runbook_resolution  TEXT,
    rag_complaint       TEXT,
    rag_resolution      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);