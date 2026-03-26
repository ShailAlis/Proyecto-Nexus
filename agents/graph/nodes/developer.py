from __future__ import annotations

import json
import re

from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

SYSTEM_PROMPT = """Eres el Agente Desarrollador de NEXUS, un sistema multiagente de desarrollo asistido por IA.

Tu responsabilidad es generar codigo de alta calidad basandote en las subtareas del Agente Analista.

Dado el analisis previo, debes producir:
1. **files**: Lista de archivos a crear o modificar, cada uno con path, language y content.
2. **tests**: Lista de tests unitarios propuestos para validar los cambios.
3. **documentation**: Notas de documentacion relevantes para los cambios.

Responde SIEMPRE en JSON valido con esta estructura:
{
  "files": [{"path": "...", "language": "...", "content": "..."}],
  "tests": [{"path": "...", "description": "...", "content": "..."}],
  "documentation": "..."
}

Reglas:
- No inventes frameworks, stacks o convenciones no mencionadas en el analisis o la descripcion.
- Si no hay evidencia clara de UI frontend, no propongas componentes frontend.
- Los paths deben ser plausibles y coherentes con el stack sugerido por la peticion.
- Prioriza cambios minimos, mantenibles y alineados con los requisitos originales."""


def developer_node(state: NexusState) -> NexusState:
    print(f">>> [DEVELOPER] Iniciando para job {state['job_id']}", flush=True)
    print(">>> [DEVELOPER] Usando modelo qwen2.5-coder:14b", flush=True)

    llm = ChatOllama(
        model="qwen2.5-coder:14b",
        temperature=0.2,
        base_url="http://ollama:11434",
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
        return {"files": [], "tests": [], "documentation": text.strip()}

    response = llm.invoke(messages)
    output = extract_json(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="developer",
        output=output,
        model_used="qwen2.5-coder:14b",
    )

    state["developer_output"] = output
    state["current_agent"] = "reviewer"
    print(f">>> [DEVELOPER] Completado para job {state['job_id']}", flush=True)
    return state
