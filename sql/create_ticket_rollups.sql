CREATE TABLE IF NOT EXISTS ticket_rollups (
    id UUID PRIMARY KEY,
    period_label VARCHAR(50) NOT NULL,
    granularity VARCHAR(20) NOT NULL,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    ticket_count INTEGER NOT NULL DEFAULT 0,
    resolved_ticket_count INTEGER NOT NULL DEFAULT 0,
    resolution_rate FLOAT NOT NULL DEFAULT 0.0,
    average_sentiment FLOAT,
    average_escalation_risk FLOAT,
    critical_escalation_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ticket_rollups_period_label ON ticket_rollups(period_label);
CREATE INDEX IF NOT EXISTS idx_ticket_rollups_granularity ON ticket_rollups(granularity);
