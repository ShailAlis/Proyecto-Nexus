from __future__ import annotations

import json
import os
import re

from langchain_anthropic import ChatAnthropic

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
    print(f">>> [DESIGNER] Iniciando para job {state['job_id']}", flush=True)
    print(f">>> [DESIGNER] Usando modelo claude-sonnet-4-20250514", flush=True)

    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.3,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
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
            "components": [],
            "visual_changes": [],
            "design_tokens": {"colors": {}, "typography": {}, "spacing": {}},
            "interaction_notes": text.strip()
        }

    response = llm.invoke(messages)
    output = extract_json(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="designer",
        output=output,
        model_used="claude-sonnet-4-20250514",
    )

    try:
        from db import get_job_epic_key
        from jira_client import post_results_comment
        epic_key = get_job_epic_key(state["job_id"])
        if epic_key:
            post_results_comment(epic_key, "Diseñador", "claude-sonnet-4-20250514", output)
            print(f">>> Resultados Diseñador publicados en Jira {epic_key}", flush=True)
    except Exception as e:
        print(f">>> Error publicando en Jira: {e}", flush=True)

    state["designer_output"] = output
    state["current_agent"] = "reviewer"
    print(f">>> [DESIGNER] Completado para job {state['job_id']}", flush=True)
    return state
