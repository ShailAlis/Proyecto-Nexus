from __future__ import annotations

import logging
import os
import re

import httpx

from db import get_job_data, save_decision, update_job_status

logger = logging.getLogger("nexus.approval")

JOB_ID_PATTERN = re.compile(r"\*\*Job:\*\*\s*`([^`]+)`")


def extract_job_id_from_message(message_content: str) -> str | None:
    """Extrae el job_id del mensaje de aprobación de Discord."""
    match = JOB_ID_PATTERN.search(message_content)
    return match.group(1) if match else None


async def _notify_n8n(job_id: str, status: str) -> None:
    """Envía callback a n8n con el resultado de la decisión."""
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
    """Dispara el workflow nexus-pr.yml via GitHub API workflow_dispatch."""
    github_token = os.getenv("GIT_TOKEN")
    github_repo = os.getenv("GIT_REPO")
    if not github_token or not github_repo:
        logger.warning("GITHUB_TOKEN o GITHUB_REPO no configurados, skip PR workflow")
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
    """Envía un mensaje a un canal de Discord por su ID (variable de entorno)."""
    from discord_bot import bot

    channel_id = os.getenv(channel_env)
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if channel:
        await channel.send(message)


async def approve_job(job_id: str, user_id: str, approval_type: str = "architecture") -> None:
    """Aprueba un job: actualiza BD, registra decisión, relanza grafo en phase=development."""
    update_job_status(job_id, "approved")
    save_decision(
        job_id=job_id,
        decision_type=approval_type,
        decided_by=user_id,
        rationale="Aprobado vía Discord",
    )
    logger.info("Job %s aprobado por %s (tipo: %s)", job_id, user_id, approval_type)

    # Obtener datos del job
    job_data = get_job_data(job_id)
    if not job_data:
        logger.error("No se encontraron datos para job %s, no se puede continuar", job_id)
        await _notify_n8n(job_id, approval_type)
        return

    if approval_type == "architecture":
        # Aprobación de análisis → relanzar grafo en phase=development
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://agents:8000/run",
                    json={
                        "job_id": job_id,
                        "jira_issue": job_data["jira_issue"],
                        "description": job_data["analyst_output"].get("scope", ""),
                        "phase": "development",
                        "analyst_output": job_data["analyst_output"],
                    },
                    timeout=10,
                )
            logger.info("Grafo relanzado en phase=development para job %s", job_id)
        except Exception:
            logger.exception("Error relanzando grafo para job %s", job_id)

    elif approval_type == "visual":
        # Aprobación final → disparar workflow de PR en GitHub
        scope = job_data["analyst_output"].get("scope", "Cambios generados por NEXUS")
        await _trigger_pr_workflow(job_id, job_data["jira_issue"], scope)

    await _notify_n8n(job_id, approval_type)


async def reject_job(
    job_id: str, decided_by: str = "unknown", reason: str = "Sin motivo especificado"
) -> None:
    """Rechaza un job: actualiza BD, registra decisión, notifica canal de errores y n8n."""
    update_job_status(job_id, "rejected")
    save_decision(
        job_id=job_id,
        decision_type="architecture",
        decided_by=decided_by,
        rationale=reason,
    )
    await _notify_channel(
        "DISCORD_ERRORS_CHANNEL_ID",
        f"\u26a0\ufe0f **Job rechazado:** `{job_id}`\n**Por:** {decided_by}\n**Motivo:** {reason}",
    )
    await _notify_n8n(job_id, "rejected")
    logger.info("Job %s rechazado por %s: %s", job_id, decided_by, reason)


async def iterate_job(
    job_id: str, decided_by: str = "unknown", comment: str = ""
) -> None:
    """Envía un job a iteración: actualiza BD, registra comentario, relanza grafo."""
    update_job_status(job_id, "pending")
    save_decision(
        job_id=job_id,
        decision_type="architecture",
        decided_by=decided_by,
        rationale=comment,
    )

    # Relanzar el grafo con contexto adicional
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "http://localhost:8000/webhook/callback",
                json={
                    "job_id": job_id,
                    "result": {"iterate_comment": comment},
                    "approval": "iterate",
                    "decided_by": decided_by,
                },
                timeout=10,
            )
    except Exception:
        logger.exception("Error relanzando grafo para job %s", job_id)

    logger.info("Job %s enviado a iteración por %s: %s", job_id, decided_by, comment)



