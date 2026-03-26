from __future__ import annotations

import json
import re

from langchain_ollama import ChatOllama

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
    print(f">>> [DEVELOPER] Iniciando para job {state['job_id']}", flush=True)
    print(f">>> [DEVELOPER] Usando modelo qwen2.5-coder:14b", flush=True)

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
            "files": [],
            "tests": [],
            "documentation": text.strip()
        }

    response = llm.invoke(messages)
    output = extract_json(response.content)

    save_agent_result(
        job_id=state["job_id"],
        agent_name="developer",
        output=output,
        model_used="qwen2.5-coder:14b",
    )

    try:
        from db import get_job_epic_key
        from jira_client import post_results_comment
        epic_key = get_job_epic_key(state["job_id"])
        if epic_key:
            post_results_comment(epic_key, "Desarrollador", "qwen2.5-coder:14b", output)
            print(f">>> Resultados Dev publicados en Jira {epic_key}", flush=True)
    except Exception as e:
        print(f">>> Error publicando en Jira: {e}", flush=True)

    state["developer_output"] = output
    state["current_agent"] = "reviewer"
    print(f">>> [DEVELOPER] Completado para job {state['job_id']}", flush=True)
    return state
