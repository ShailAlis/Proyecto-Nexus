from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

from db import save_agent_result
from graph.state import NexusState

SYSTEM_PROMPT = """Eres el Agente Diseñador de NEXUS, un sistema multiagente de desarrollo asistido por IA.

Tu responsabilidad es generar especificaciones de UI/UX basándote en las subtareas del Agente Analista.

Dado el análisis previo, debes producir:
1. **components**: Lista de componentes UI afectados o nuevos.
2. **visual_changes**: Descripción de cambios visuales necesarios.
3. **design_tokens**: Tokens de diseño relevantes (colores, tipografías, espaciados).
4. **interaction_notes**: Notas sobre interacciones, animaciones o estados.

Responde SIEMPRE en JSON válido con esta estructura:
{
  "components": ["..."],
  "visual_changes": ["..."],
  "design_tokens": {"colors": {}, "typography": {}, "spacing": {}},
  "interaction_notes": "..."
}"""


def designer_node(state: NexusState) -> NexusState:
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.3,
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
        agent_name="designer",
        output=output,
        model_used="gpt-4o",
    )

    state["designer_output"] = output
    state["current_agent"] = "reviewer"
    return state
