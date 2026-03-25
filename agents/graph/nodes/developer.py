from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

from db import save_agent_result
from graph.state import NexusState

SYSTEM_PROMPT = """Eres el Agente Desarrollador de NEXUS, un sistema multiagente de desarrollo asistido por IA.

Tu responsabilidad es generar código de alta calidad basándote en las subtareas del Agente Analista.

Dado el análisis previo, debes producir:
1. **files**: Lista de archivos a crear o modificar, cada uno con path, language y content.
2. **tests**: Lista de tests unitarios propuestos para validar los cambios.
3. **documentation**: Notas de documentación relevantes para los cambios.

Responde SIEMPRE en JSON válido con esta estructura:
{
  "files": [{"path": "...", "language": "...", "content": "..."}],
  "tests": [{"path": "...", "description": "...", "content": "..."}],
  "documentation": "..."
}"""


def developer_node(state: NexusState) -> NexusState:
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.2,
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    analyst = json.dumps(state["analyst_output"], ensure_ascii=False)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Issue Jira: {state['jira_issue']}\n\n"
                f"Descripción:\n{state['description']}\n\n"
                f"Análisis del Agente Analista:\n{analyst}"
            ),
        },
    ]

    response = llm.invoke(messages)
    output = json.loads(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="developer",
        output=output,
        model_used="gpt-4o",
    )

    state["developer_output"] = output
    state["current_agent"] = "reviewer"
    return state
