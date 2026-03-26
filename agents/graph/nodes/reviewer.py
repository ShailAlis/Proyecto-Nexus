from __future__ import annotations

import json
import os
import re

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

REVIEW_PROMPT = """Eres un revisor experto del sistema NEXUS. Analiza los outputs del desarrollador y diseñador.

Evalúa:
- Calidad y corrección del código propuesto
- Coherencia entre código y especificación de diseño
- Posibles problemas de seguridad, rendimiento o mantenibilidad
- Alineación con los requisitos originales del analista

Responde en JSON válido:
{{
  "score": 0-100,
  "issues": ["..."],
  "suggestions": ["..."],
  "approved": true/false
}}"""


def _build_context(state: NexusState) -> str:
    return (
        f"Issue Jira: {state['jira_issue']}\n\n"
        f"Descripción original:\n{state['description']}\n\n"
        f"Output del Analista:\n{json.dumps(state['analyst_output'], ensure_ascii=False)}\n\n"
        f"Output del Desarrollador:\n{json.dumps(state['developer_output'], ensure_ascii=False)}\n\n"
        f"Output del Diseñador:\n{json.dumps(state['designer_output'], ensure_ascii=False)}"
    )


def reviewer_node(state: NexusState) -> NexusState:
    context = _build_context(state)

    messages = [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": context},
    ]

    # Revisión con Ollama (DeepSeek)
    ollama_llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.1,
        base_url="http://ollama:11434",
    )
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
            "score": 0,
            "issues": [],
            "suggestions": [],
            "approved": False
        }

    ollama_response = ollama_llm.invoke(messages)
    ollama_review = extract_json(ollama_response.content)

    # Revisión con Anthropic (Claude)
    anthropic_llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.1,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    anthropic_response = anthropic_llm.invoke(messages)
    anthropic_review = extract_json(anthropic_response.content)

    # Comparar ambas revisiones
    consensus = ollama_review.get("approved") == anthropic_review.get("approved")

    discrepancies = []
    if not consensus:
        discrepancies.append(
            f"DeepSeek approved={ollama_review.get('approved')}, "
            f"Anthropic approved={anthropic_review.get('approved')}"
        )

    ollama_issues = set(ollama_review.get("issues", []))
    anthropic_issues = set(anthropic_review.get("issues", []))
    only_ollama = ollama_issues - anthropic_issues
    only_anthropic = anthropic_issues - ollama_issues
    if only_ollama:
        discrepancies.append(f"Issues solo DeepSeek: {list(only_ollama)}")
    if only_anthropic:
        discrepancies.append(f"Issues solo Anthropic: {list(only_anthropic)}")

    recommendation = "approve" if consensus and ollama_review.get("approved") else "review_required"

    output = {
        "ollama_review": ollama_review,
        "anthropic_review": anthropic_review,
        "consensus": consensus,
        "discrepancies": discrepancies,
        "recommendation": recommendation,
    }

    save_agent_result(
        job_id=state["job_id"],
        agent_name="reviewer",
        output=output,
        model_used="deepseek-r1:14b+claude-sonnet",
    )

    state["reviewer_output"] = output
    state["current_agent"] = "approval_gate"

    # Si no hay consenso, aprobación humana obligatoria
    if not consensus:
        state["approval_required"] = True
        state["approval_type"] = "review_discrepancy"

    return state
