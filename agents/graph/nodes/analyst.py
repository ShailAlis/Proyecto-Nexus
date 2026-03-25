from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

from db import save_agent_result
from graph.state import NexusState

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
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.2,
        api_key=os.getenv("OPENAI_API_KEY"),
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

    response = llm.invoke(messages)
    output = json.loads(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="analyst",
        output=output,
        model_used="gpt-4o",
    )

    state["analyst_output"] = output
    state["current_agent"] = "developer"
    return state
