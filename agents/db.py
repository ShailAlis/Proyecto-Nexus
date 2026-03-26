from __future__ import annotations

import json
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def _get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def create_job(job_id: str, jira_issue: str, trigger_type: str = "manual") -> None:
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nexus_jobs (job_id, jira_issue, status, trigger_type)
                VALUES (%s, %s, 'pending', %s)
                ON CONFLICT (job_id) DO NOTHING
                """,
                (job_id, jira_issue, trigger_type),
            )
        conn.commit()
    finally:
        conn.close()


def save_agent_result(
    job_id: str,
    agent_name: str,
    output: dict,
    model_used: str,
    tokens_used: int | None = None,
) -> None:
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nexus_agent_results (job_id, agent_name, output, model_used, tokens_used)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (job_id, agent_name, json.dumps(output), model_used, tokens_used),
            )
        conn.commit()
    finally:
        conn.close()


def update_job_status(job_id: str, status: str) -> None:
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE nexus_jobs SET status = %s WHERE job_id = %s",
                (status, job_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_job_status(job_id: str) -> dict | None:
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, jira_issue, status, trigger_type, created_at,
                       approved_by, approved_at
                FROM nexus_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "job_id": str(row[0]),
                "jira_issue": row[1],
                "status": row[2],
                "trigger_type": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "approved_by": row[5],
                "approved_at": row[6].isoformat() if row[6] else None,
            }
    finally:
        conn.close()


def get_job_data(job_id: str) -> dict | None:
    """Devuelve jira_issue, description (del analyst) y analyst_output de un job."""
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Datos básicos del job
            cur.execute(
                "SELECT jira_issue FROM nexus_jobs WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            jira_issue = row[0]

            # Output del analista
            cur.execute(
                """
                SELECT output FROM nexus_agent_results
                WHERE job_id = %s AND agent_name = 'analyst'
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_id,),
            )
            analyst_row = cur.fetchone()
            analyst_output = analyst_row[0] if analyst_row else {}
            if isinstance(analyst_output, str):
                analyst_output = json.loads(analyst_output)

            return {
                "job_id": job_id,
                "jira_issue": jira_issue,
                "analyst_output": analyst_output,
            }
    finally:
        conn.close()


def save_decision(
    job_id: str,
    decision_type: str,
    decided_by: str,
    rationale: str | None = None,
) -> None:
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nexus_decisions (job_id, decision_type, rationale, decided_by)
                VALUES (%s, %s, %s, %s)
                """,
                (job_id, decision_type, rationale, decided_by),
            )
        conn.commit()
    finally:
        conn.close()


def get_job_epic_key(job_id: str) -> str | None:
    """Obtiene el epic_key de Jira asociado a un job."""
    job_id = str(job_id).lstrip('=').strip()
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT output->>'jira_epic_key'
                FROM nexus_agent_results
                WHERE job_id = %s AND agent_name = 'analyst'
                LIMIT 1
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()
