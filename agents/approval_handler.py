from __future__ import annotations

import json
import logging
import os
import re

import httpx
import psycopg2

from db import get_job_data, save_decision, update_job_status

logger = logging.getLogger("nexus.approval")

JOB_ID_PATTERN = re.compile(r"\*\*Job:\*\*\s*`([^`]+)`")


def extract_job_id_from_message(message_content: str) -> str | None:
    match = JOB_ID_PATTERN.search(message_content)
    return match.group(1) if match else None


def _get_latest_agent_output(job_id: str, agent_name: str) -> dict:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {}

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT output
                FROM nexus_agent_results
                WHERE job_id = %s AND agent_name = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id, agent_name),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return {}
            output = row[0]
            if isinstance(output, str):
                return json.loads(output)
            return output
    finally:
        conn.close()


async def _notify_n8n(job_id: str, status: str) -> None:
    n8n_url = os.getenv("N8N_WEBHOOK_URL")
    if not n8n_url:
        logger.warning("N8N_WEBHOOK_URL no configurado, skip callback")
        return

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                n8n_url,
                json={"job_id": job_id, "result": {}, "approval": status},
                timeout=10,
            )
    except Exception:
        logger.exception("Error notificando a n8n para job %s", job_id)


async def _trigger_pr_workflow(job_id: str, jira_issue: str, summary: str) -> None:
    github_token = os.getenv("GIT_TOKEN")
    github_repo = os.getenv("GIT_REPO")
    if not github_token or not github_repo:
        logger.warning("GIT_TOKEN o GIT_REPO no configurados, skip PR workflow")
        return

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.github.com/repos/{github_repo}/actions/workflows/nexus-pr.yml/dispatches",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={
                    "ref": "develop",
                    "inputs": {
                        "job_id": job_id,
                        "jira_issue": jira_issue,
                        "branch_name": job_id,
                        "pr_title": f"feat({jira_issue}): {summary[:60]}",
                        "pr_body": f"Job NEXUS `{job_id}` completado y aprobado.\n\nResumen: {summary}",
                    },
                },
                timeout=15,
            )
        logger.info("Workflow nexus-pr.yml disparado para job %s", job_id)
    except Exception:
        logger.exception("Error disparando workflow PR para job %s", job_id)


async def _notify_channel(channel_env: str, message: str) -> None:
    from discord_bot import bot

    channel_id = os.getenv(channel_env)
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if channel:
        await channel.send(message)


async def approve_job(job_id: str, user_id: str, approval_type: str = "architecture") -> None:
    update_job_status(job_id, "approved")
    reviewer_output = _get_latest_agent_output(job_id, "reviewer")
    is_final_review = bool(reviewer_output)
    decision_type = "visual" if is_final_review or approval_type == "visual" else "architecture"

    save_decision(
        job_id=job_id,
        decision_type=decision_type,
        decided_by=user_id,
        rationale="Aprobado via Discord",
    )
    logger.info("Job %s aprobado por %s (tipo: %s)", job_id, user_id, decision_type)

    job_data = get_job_data(job_id)
    if not job_data:
        logger.error("No se encontraron datos para job %s, no se puede continuar", job_id)
        await _notify_n8n(job_id, approval_type)
        return

    if not is_final_review:
        try:
            original_description = (
                job_data["analyst_output"].get("original_description")
                or job_data["analyst_output"].get("scope", "")
            )
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://agents:8000/run",
                    json={
                        "job_id": job_id,
                        "jira_issue": job_data["jira_issue"],
                        "description": original_description,
                        "phase": "development",
                        "analyst_output": job_data["analyst_output"],
                    },
                    timeout=10,
                )
            logger.info("Grafo relanzado en phase=development para job %s", job_id)
        except Exception:
            logger.exception("Error relanzando grafo para job %s", job_id)
    else:
        scope = job_data["analyst_output"].get("scope", "Cambios generados por NEXUS")
        await _trigger_pr_workflow(job_id, job_data["jira_issue"], str(scope))
        update_job_status(job_id, "done")

    await _notify_n8n(job_id, decision_type)


async def reject_job(job_id: str, decided_by: str = "unknown", reason: str = "Sin motivo especificado") -> None:
    reviewer_output = _get_latest_agent_output(job_id, "reviewer")
    decision_type = "visual" if reviewer_output else "architecture"
    update_job_status(job_id, "rejected")
    save_decision(
        job_id=job_id,
        decision_type=decision_type,
        decided_by=decided_by,
        rationale=reason,
    )
    await _notify_channel(
        "DISCORD_ERRORS_CHANNEL_ID",
        f"⚠️ **Job rechazado:** `{job_id}`\n**Por:** {decided_by}\n**Motivo:** {reason}",
    )
    await _notify_n8n(job_id, decision_type)
    logger.info("Job %s rechazado por %s: %s", job_id, decided_by, reason)


async def iterate_job(job_id: str, decided_by: str = "unknown", comment: str = "") -> None:
    update_job_status(job_id, "pending")

    job_data = get_job_data(job_id)
    if not job_data:
        logger.error("No se encontraron datos para job %s, no se puede iterar", job_id)
        return

    original_description = (
        job_data["analyst_output"].get("original_description")
        or job_data["analyst_output"].get("scope", "")
    )

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "http://agents:8000/run",
                json={
                    "job_id": job_id,
                    "jira_issue": job_data["jira_issue"],
                    "description": original_description,
                    "phase": "development",
                    "analyst_output": job_data["analyst_output"],
                    "iteration_comment": comment,
                },
                timeout=10,
            )
    except Exception:
        logger.exception("Error relanzando grafo para job %s", job_id)

    logger.info("Job %s enviado a iteracion por %s: %s", job_id, decided_by, comment)
