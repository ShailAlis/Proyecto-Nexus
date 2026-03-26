from __future__ import annotations

import json
import logging
import re

import httpx
from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

logger = logging.getLogger("nexus.analyst")

ANALYST_SYSTEM_PROMPT = """Eres un arquitecto de software senior especializado en análisis técnico.
Tu trabajo es descomponer peticiones de desarrollo en tareas concretas y accionables.

INSTRUCCIONES CRITICAS:
- Debes responder UNICAMENTE con JSON valido, sin texto adicional
- Si la descripcion es vaga, infiere los detalles tecnicos necesarios
- NUNCA devuelvas campos vacios - si no tienes informacion, usa valores por defecto razonables
- Los subtasks deben ser tareas tecnicas concretas y especificas

FORMATO DE RESPUESTA OBLIGATORIO:
```json
{
  "subtasks": ["tarea 1 concreta", "tarea 2 concreta", "tarea 3 concreta"],
  "affected_modules": ["modulo1", "modulo2"],
  "complexity": "low|medium|high",
  "scope": "descripcion clara del alcance tecnico"
}
```
"""


def extract_json(text: str) -> dict:
    """Extrae JSON de la respuesta del modelo, limpiando tags <think> y bloques markdown."""
    # Elimina bloques <think>...</think> de deepseek-r1
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Busca bloque ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Busca JSON directo { ... }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    # Devuelve estructura por defecto si no encuentra JSON
    return {
        "subtasks": [],
        "affected_modules": [],
        "complexity": "medium",
        "scope": text.strip()
    }


def analyst_node(state: NexusState) -> NexusState:
    print(f">>> [ANALYST] job_id: {state['job_id']}", flush=True)
    print(f">>> [ANALYST] jira_issue: {state['jira_issue']}", flush=True)
    print(f">>> [ANALYST] description: {state['description'][:200]}", flush=True)

    llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.2,
        base_url="http://ollama:11434",
    )

    messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Analiza esta petición de desarrollo y descomponla en tareas técnicas:

PETICIÓN: {state['jira_issue']}
DESCRIPCIÓN: {state['description']}

Genera un análisis técnico detallado con subtareas específicas e implementables.
Responde SOLO con el JSON, sin explicaciones adicionales."""
        },
    ]

    response = llm.invoke(messages)
    output = extract_json(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="analyst",
        output=output,
        model_used="deepseek-r1:14b",
    )

    state["analyst_output"] = output
    state["current_agent"] = "developer"

    # Crear epica y subtareas en Jira
    try:
        from jira_client import create_epic, create_subtask

        epic = create_epic(
            summary=f"[NEXUS] {state['jira_issue']}",
            description=state["description"],
        )
        print(f">>> Epica creada en Jira: {epic['key']}", flush=True)

        subtasks = output.get("subtasks", [])
        created_tasks = []
        for subtask in subtasks[:5]:  # maximo 5 subtareas
            task = create_subtask(
                summary=subtask if isinstance(subtask, str) else subtask.get("title", str(subtask)),
                description=str(subtask),
                epic_key=epic["key"],
            )
            created_tasks.append(task["key"])
            print(f">>> Subtarea creada: {task['key']}", flush=True)

        output["jira_epic_key"] = epic["key"]
        output["jira_subtasks"] = created_tasks
        state["analyst_output"] = output
    except Exception as e:
        import traceback
        print(f">>> ERROR creando issues en Jira: {e}", flush=True)
        traceback.print_exc()
        print(f"No se pudieron crear issues en Jira para job {state['job_id']}")

    # Solicitar aprobacion de arquitectura via Discord
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

    return state
