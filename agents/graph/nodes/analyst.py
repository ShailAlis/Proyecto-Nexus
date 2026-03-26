from __future__ import annotations

import json
import logging
import re

import httpx
from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

logger = logging.getLogger("nexus.analyst")

SYSTEM_PROMPT = """Eres un arquitecto de software senior especializado en analisis tecnico.
Tu trabajo es descomponer peticiones de desarrollo en tareas concretas y accionables.

INSTRUCCIONES CRITICAS:
- Debes responder UNICAMENTE con JSON valido, sin texto adicional.
- Si la descripcion es vaga, infiere solo detalles tecnicos razonables.
- NUNCA devuelvas campos vacios: usa valores por defecto utiles y conservadores.
- Los subtasks deben ser tareas tecnicas concretas, especificas y ejecutables.
- No inventes frameworks, lenguajes o arquitecturas no mencionadas en la peticion.

FORMATO DE RESPUESTA OBLIGATORIO:
{
  "subtasks": ["tarea tecnica concreta 1", "tarea tecnica concreta 2", "tarea tecnica concreta 3"],
  "affected_modules": ["modulo1", "modulo2"],
  "complexity": "low|medium|high|critical",
  "scope": "descripcion clara del alcance tecnico, supuestos y limites"
}"""


def extract_json(text: str) -> dict:
    """Extrae JSON de la respuesta del modelo, limpiando tags <think> y bloques markdown."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return {
        "subtasks": [],
        "affected_modules": [],
        "complexity": "medium",
        "scope": text.strip(),
    }


def analyst_node(state: NexusState) -> NexusState:
    print(f">>> [ANALYST] Iniciando para job {state['job_id']}", flush=True)
    print(f">>> [ANALYST] job_id: {state['job_id']}", flush=True)
    print(f">>> [ANALYST] jira_issue: {state['jira_issue']}", flush=True)
    print(f">>> [ANALYST] description: {state['description'][:200]}", flush=True)
    print(">>> [ANALYST] Usando modelo deepseek-r1:14b", flush=True)

    llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.2,
        base_url="http://ollama:11434",
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Analiza esta peticion de desarrollo y descomponla en tareas tecnicas:

PETICION: {state['jira_issue']}
DESCRIPCION: {state['description']}

Genera un analisis tecnico detallado con subtareas especificas e implementables.
Responde SOLO con el JSON, sin explicaciones adicionales.""",
        },
    ]

    response = llm.invoke(messages)
    output = extract_json(response.content)
    output["original_description"] = state["description"]
    output["original_jira_issue"] = state["jira_issue"]

    save_agent_result(
        job_id=state["job_id"],
        agent_name="analyst",
        output=output,
        model_used="deepseek-r1:14b",
    )

    state["analyst_output"] = output
    state["current_agent"] = "developer"

    try:
        httpx.post(
            "http://agents:8000/notify/approval-required",
            json={
                "job_id": state["job_id"],
                "approval_type": "architecture",
                "summary": output.get("scope", "Analisis completado"),
            },
            timeout=5,
        )
    except Exception:
        logger.warning("No se pudo enviar notificacion de aprobacion para job %s", state["job_id"])

    print(f">>> [ANALYST] Completado para job {state['job_id']}", flush=True)
    return state
