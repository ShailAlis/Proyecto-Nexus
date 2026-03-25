from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid

import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from db import get_job_status, save_decision, update_job_status
from graph.graph import run_graph
from graph.state import NexusState

load_dotenv()

logger = logging.getLogger("nexus.main")

redis_client: redis.Redis | None = None
_discord_thread: threading.Thread | None = None


def _start_discord_bot() -> None:
    print(">>> _start_discord_bot iniciado")
    try:
        from discord_bot import run_bot_in_loop
        print(">>> Importado discord_bot OK")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print(">>> Loop creado, arrancando...")
        run_bot_in_loop(loop)
    except Exception as e:
        print(f">>> ERROR CRITICO: {e}")
        import traceback
        traceback.print_exc()


app = FastAPI(title="NEXUS Agents", version="0.1.0")


@app.on_event("startup")
async def startup_event():
    print(">>> startup_event ejecutándose")
    global _discord_thread, redis_client
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
    token = os.getenv("DISCORD_BOT_TOKEN")
    print(f">>> Token Discord presente: {bool(token)}")
    if token:
        _discord_thread = threading.Thread(target=_start_discord_bot, daemon=True)
        _discord_thread.start()
        print(">>> Discord thread lanzado")
    else:
        print(">>> Sin token Discord")


# ---------- Schemas ----------


class RunRequest(BaseModel):
    job_id: str | None = None
    jira_issue: str
    description: str


class RunResponse(BaseModel):
    job_id: str
    status: str


class CallbackPayload(BaseModel):
    job_id: str
    result: dict
    approval: str | None = None
    decided_by: str | None = None


class ApprovalNotification(BaseModel):
    job_id: str
    approval_type: str
    summary: str


# ---------- Endpoints ----------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nexus-agents"}


@app.post("/run", response_model=RunResponse)
async def run(request: RunRequest, background_tasks: BackgroundTasks):
    job_id = request.job_id or str(uuid.uuid4())

    initial_state: NexusState = {
        "job_id": job_id,
        "jira_issue": request.jira_issue,
        "description": request.description,
        "analyst_output": {},
        "developer_output": {},
        "designer_output": {},
        "reviewer_output": {},
        "current_agent": "analyst",
        "status": "running",
        "approval_required": False,
        "approval_type": "",
        "error": None,
    }

    update_job_status(job_id, "running")
    background_tasks.add_task(run_graph, initial_state)

    return RunResponse(job_id=job_id, status="running")


@app.get("/status/{job_id}")
async def status(job_id: str):
    result = get_job_status(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.post("/webhook/callback")
async def webhook_callback(payload: CallbackPayload):
    """Recibe resultado del grafo o decisión humana y notifica a n8n."""
    if payload.approval:
        save_decision(
            job_id=payload.job_id,
            decision_type=payload.approval,
            decided_by=payload.decided_by or "unknown",
        )
        new_status = "approved" if payload.approval != "rejected" else "rejected"
        update_job_status(payload.job_id, new_status)
    else:
        update_job_status(payload.job_id, "done")

    # TODO: notificar a n8n vía webhook cuando esté configurado
    return {"received": True, "job_id": payload.job_id}


@app.post("/notify/approval-required")
async def notify_approval_required(notification: ApprovalNotification):
    """Envía solicitud de aprobación al canal de Discord."""
    from discord_bot import client, send_approval_request

    if not client.is_ready():
        raise HTTPException(status_code=503, detail="Discord bot not ready")

    asyncio.run_coroutine_threadsafe(
        send_approval_request(
            job_id=notification.job_id,
            approval_type=notification.approval_type,
            summary=notification.summary,
        ),
        client.loop,
    )
    return {"sent": True, "job_id": notification.job_id}
