from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from db import get_job_status, save_decision, update_job_status
from graph.graph import run_graph
from graph.state import NexusState

load_dotenv()

redis_client: redis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    yield
    if redis_client:
        redis_client.close()


app = FastAPI(title="NEXUS Agents", version="0.1.0", lifespan=lifespan)


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
