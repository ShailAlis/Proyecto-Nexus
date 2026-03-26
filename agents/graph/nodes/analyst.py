from __future__ import annotations

import json
import logging
import re

import httpx
from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

logger = logging.getLogger("nexus.analyst")

SYSTEM_PROMPT = """Eres el Agente Analista de NEXUS, un sistema multiagente de desarrollo asistido por IA.

Tu responsabilidad es descomponer requisitos de negocio en especificaciones técnicas accionables.

Dado un issue de Jira con su descripción, debes producir:
1. **subtasks**: Lista de subtareas técnicas concretas y atómicas.
2. **affected_modules**: Módulos del sistema que se verán afectados.
3. **complexity**: Estimación de complejidad (low, medium, high, critical).
4. **scope**: Resumen del alcance del cambio.

Responde SIEMPRE en JSON válido con esta estructura:
{
  "subtasks": ["..."],
  "affected_modules": ["..."],
  "complexity": "medium",
  "scope": "..."
}"""


def analyst_node(state: NexusState) -> NexusState:
    llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.2,
        base_url="http://ollama:11434",
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Issue Jira: {state['jira_issue']}\n\n"
                f"Descripción:\n{state['description']}"
            ),
        },
    ]

    def extract_json(text: str) -> dict:
        # Elimina bloques <think>...</think> de deepseek-r1
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # Busca bloque ```json ... ```
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Busca JSON directo { ... }
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Devuelve estructura por defecto si no encuentra JSON
        return {
            "subtasks": [],
            "affected_modules": [],
            "complexity": "medium",
            "scope": text.strip()
        }

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

    # Solicitar aprobación de arquitectura vía Discord
    try:
        httpx.post(
            "http://agents:8000/notify/approval-required",
            json={
                "job_id": state["job_id"],
                "approval_type": "architecture",
                "summary": output.get("scope", "Análisis completado"),
            },
            timeout=5,
        )
    except Exception:
        logger.warning("No se pudo enviar notificación de aprobación para job %s", state["job_id"])

    return state

