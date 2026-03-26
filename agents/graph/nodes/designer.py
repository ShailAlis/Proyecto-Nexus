from __future__ import annotations

import json
import os
import re

from langchain_anthropic import ChatAnthropic

from db import save_agent_result
from graph.state import NexusState

SYSTEM_PROMPT = """Eres el Agente Disenador de NEXUS, un sistema multiagente de desarrollo asistido por IA.

Tu responsabilidad es generar especificaciones de UI/UX basandote en las subtareas del Agente Analista.

Dado el analisis previo, debes producir:
1. **components**: Lista de componentes UI afectados o nuevos.
2. **visual_changes**: Descripcion de cambios visuales necesarios.
3. **design_tokens**: Tokens de diseno relevantes (colores, tipografias, espaciados).
4. **interaction_notes**: Notas sobre interacciones, animaciones o estados.

Responde SIEMPRE en JSON valido con esta estructura:
{
  "components": ["..."],
  "visual_changes": ["..."],
  "design_tokens": {"colors": {}, "typography": {}, "spacing": {}},
  "interaction_notes": "..."
}

Reglas:
- Si la peticion no implica interfaz de usuario, devuelve cambios visuales minimos y explicalo en interaction_notes.
- No inventes frameworks visuales ajenos al proyecto.
- Mantente alineado con la descripcion original y con el analisis tecnico."""


def designer_node(state: NexusState) -> NexusState:
    print(f">>> [DESIGNER] Iniciando para job {state['job_id']}", flush=True)
    print(">>> [DESIGNER] Usando modelo claude-sonnet-4-20250514", flush=True)

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
                f"Descripcion:\n{state['description']}\n\n"
                f"Feedback de iteracion:\n{state.get('iteration_comment', '') or 'Sin feedback adicional'}\n\n"
                f"Analisis del Agente Analista:\n{analyst}"
            ),
        },
    ]

    def extract_json(text: str) -> dict:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {
            "components": [],
            "visual_changes": [],
            "design_tokens": {"colors": {}, "typography": {}, "spacing": {}},
            "interaction_notes": text.strip(),
        }

    response = llm.invoke(messages)
    output = extract_json(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="designer",
        output=output,
        model_used="claude-sonnet-4-20250514",
    )

    state["designer_output"] = output
    state["current_agent"] = "reviewer"
    print(f">>> [DESIGNER] Completado para job {state['job_id']}", flush=True)
    return state
