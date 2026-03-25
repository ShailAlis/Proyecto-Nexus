-- ============================================================
-- NEXUS — Esquema inicial de base de datos
-- PostgreSQL 15
-- ============================================================

-- Extensiones útiles
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- nexus_jobs
-- Registro maestro de cada ejecución de trabajo originada
-- en un issue de Jira.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jira_issue_key  VARCHAR(64)  NOT NULL,
    jira_summary    TEXT,
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    -- pending | running | waiting_approval | approved | rejected | completed | failed
    current_agent   VARCHAR(64),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    metadata        JSONB        DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_nexus_jobs_jira     ON nexus_jobs (jira_issue_key);
CREATE INDEX IF NOT EXISTS idx_nexus_jobs_status   ON nexus_jobs (status);
CREATE INDEX IF NOT EXISTS idx_nexus_jobs_created  ON nexus_jobs (created_at DESC);

-- Trigger: mantener updated_at automáticamente
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_nexus_jobs_updated_at
    BEFORE UPDATE ON nexus_jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ------------------------------------------------------------
-- nexus_agent_results
-- Output persistido de cada agente para cada job.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_agent_results (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID         NOT NULL REFERENCES nexus_jobs(id) ON DELETE CASCADE,
    agent_name  VARCHAR(64)  NOT NULL,
    -- analyst | developer | designer | reviewer
    status      VARCHAR(32)  NOT NULL DEFAULT 'pending',
    -- pending | running | completed | failed
    input       JSONB        DEFAULT '{}'::jsonb,
    output      JSONB        DEFAULT '{}'::jsonb,
    error       TEXT,
    tokens_used INTEGER,
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_results_job    ON nexus_agent_results (job_id);
CREATE INDEX IF NOT EXISTS idx_agent_results_agent  ON nexus_agent_results (agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_results_status ON nexus_agent_results (status);

-- ------------------------------------------------------------
-- nexus_decisions
-- Historial de decisiones humanas en los puntos de aprobación.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID         NOT NULL REFERENCES nexus_jobs(id) ON DELETE CASCADE,
    checkpoint      VARCHAR(64)  NOT NULL,
    -- architecture_approval | data_security_approval | final_approval
    decision        VARCHAR(16)  NOT NULL,
    -- approved | rejected | changes_requested
    discord_user_id VARCHAR(64),
    discord_message_id VARCHAR(64),
    notes           TEXT,
    decided_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_job         ON nexus_decisions (job_id);
CREATE INDEX IF NOT EXISTS idx_decisions_checkpoint  ON nexus_decisions (checkpoint);

-- ------------------------------------------------------------
-- nexus_context_summary
-- Resumen de contexto acumulado por issue Jira, usado para
-- mantener coherencia entre ejecuciones del mismo issue.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_context_summary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jira_issue_key  VARCHAR(64)  NOT NULL UNIQUE,
    summary         TEXT,
    key_decisions   JSONB        DEFAULT '[]'::jsonb,
    tech_stack      JSONB        DEFAULT '[]'::jsonb,
    open_questions  JSONB        DEFAULT '[]'::jsonb,
    last_job_id     UUID         REFERENCES nexus_jobs(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_jira ON nexus_context_summary (jira_issue_key);

CREATE TRIGGER trg_nexus_context_updated_at
    BEFORE UPDATE ON nexus_context_summary
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();