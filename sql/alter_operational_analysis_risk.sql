ALTER TABLE operational_analysis
    ADD COLUMN IF NOT EXISTS source_used VARCHAR(20),
    ADD COLUMN IF NOT EXISTS assigned_agent_id UUID,
    ADD COLUMN IF NOT EXISTS assigned_manager_id UUID,
    ADD COLUMN IF NOT EXISTS resolution_state VARCHAR(20),
    ADD COLUMN IF NOT EXISTS risk_processed BOOLEAN DEFAULT FALSE NOT NULL,
    ADD COLUMN IF NOT EXISTS confidence_decay_score FLOAT,
    ADD COLUMN IF NOT EXISTS momentum_score FLOAT,
    ADD COLUMN IF NOT EXISTS risk_multiplier FLOAT,
    ADD COLUMN IF NOT EXISTS risk_reason JSONB;
