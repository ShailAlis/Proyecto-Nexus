from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import create_job, get_job_status, update_job_status
from graph.graph import run_graph
from graph.state import NexusState

load_dotenv()

logger = logging.getLogger("nexus.main")
redis_client: redis.Redis | None = None

@asynccontextmanager
async def lifespan(_: FastAPI):
    global redis_client
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
    print(">>> startup_event: Redis conectado")
    yield

app = FastAPI(title="NEXUS Agents", version="0.1.0", lifespan=lifespan)

class RunRequest(BaseModel):
    job_id: str | None = None
    jira_issue: str
    description: str
    phase: str = "analysis"
    analyst_output: dict | None = None
    iteration_comment: str | None = None


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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nexus-agents"}


@app.post("/run", response_model=RunResponse)
async def run(request: RunRequest):
    job_id = request.job_id or str(uuid.uuid4())
    print(f">>> /run recibido job_id={job_id}")

    current_agent = {
        "analysis": "analyst",
        "development": "developer",
        "review": "reviewer",
    }.get(request.phase, "analyst")

    create_job(job_id, request.jira_issue, trigger_type=request.phase)

    initial_state: NexusState = {
        "job_id": job_id,
        "jira_issue": request.jira_issue,
        "description": request.description,
        "analyst_output": request.analyst_output or {},
        "developer_output": {},
        "designer_output": {},
        "reviewer_output": {},
        "current_agent": current_agent,
        "status": "running",
        "approval_required": False,
        "approval_type": "",
        "error": None,
        "phase": request.phase,
        "iteration_comment": request.iteration_comment or "",
    }

    update_job_status(job_id, "running")
    print(f">>> Job {job_id} registrado en BD, lanzando grafo...")

    asyncio.ensure_future(run_graph(initial_state))
    print(f">>> asyncio.ensure_future lanzado para {job_id}")

    return RunResponse(job_id=job_id, status="running")


@app.get("/status/{job_id}")
async def status(job_id: str):
    result = get_job_status(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.post("/webhook/callback")
async def webhook_callback(payload: CallbackPayload):
    if payload.approval == "iterate":
        update_job_status(payload.job_id, "pending")
    elif payload.approval == "rejected":
        update_job_status(payload.job_id, "rejected")
    elif payload.approval:
        update_job_status(payload.job_id, "approved")
    else:
        update_job_status(payload.job_id, "done")
    return {"received": True, "job_id": payload.job_id}


@app.post("/notify/approval-required")
async def notify_approval_required(notification: ApprovalNotification):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://nexus-bot:8001/notify",
            json={
                "job_id": notification.job_id,
                "approval_type": notification.approval_type,
                "summary": notification.summary,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    return {"status": "notified"}
