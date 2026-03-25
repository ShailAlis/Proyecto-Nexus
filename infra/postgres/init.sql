-- ============================================================
-- NEXUS — Esquema inicial de base de datos
-- PostgreSQL 15
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------
-- nexus_jobs
-- Registro maestro de cada ejecución originada en Jira.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_jobs (
    job_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jira_issue     TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN (
                       'pending', 'running', 'awaiting_approval',
                       'approved', 'rejected', 'done'
                   )),
    trigger_type   TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    approved_by    TEXT,
    approved_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_jira   ON nexus_jobs (jira_issue);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON nexus_jobs (status);

-- ------------------------------------------------------------
-- nexus_agent_results
-- Output persistido de cada agente para cada job.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_agent_results (
    result_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID REFERENCES nexus_jobs(job_id),
    agent_name  TEXT NOT NULL,
    output      JSONB,
    model_used  TEXT,
    tokens_used INT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_job   ON nexus_agent_results (job_id);
CREATE INDEX IF NOT EXISTS idx_results_agent ON nexus_agent_results (agent_name);

-- ------------------------------------------------------------
-- nexus_decisions
-- Historial de decisiones humanas en los puntos de aprobación.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_decisions (
    decision_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id        UUID REFERENCES nexus_jobs(job_id),
    decision_type TEXT CHECK (decision_type IN (
                      'architecture', 'data', 'security', 'visual'
                  )),
    rationale     TEXT,
    decided_by    TEXT,
    decided_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_job ON nexus_decisions (job_id);

-- ------------------------------------------------------------
-- nexus_context_summary
-- Resumen de contexto acumulado por issue Jira.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_context_summary (
    summary_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jira_issue    TEXT UNIQUE NOT NULL,
    summary       TEXT,
    key_decisions TEXT[],
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_jira ON nexus_context_summary (jira_issue);
