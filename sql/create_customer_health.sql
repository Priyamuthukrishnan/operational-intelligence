CREATE TABLE IF NOT EXISTS customer_health (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL UNIQUE,
    health_score FLOAT NOT NULL DEFAULT 100.0,
    sentiment_average FLOAT,
    escalation_risk_average FLOAT,
    repeat_issue_frequency FLOAT,
    resolution_rate FLOAT,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_health_customer_id ON customer_health(customer_id);