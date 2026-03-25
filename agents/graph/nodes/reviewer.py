from __future__ import annotations

import json
import os

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

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

    # Revisión con OpenAI
    openai_llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.1,
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    openai_response = openai_llm.invoke(messages)
    openai_review = json.loads(openai_response.content)

    # Revisión con Anthropic
    anthropic_llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.1,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    anthropic_response = anthropic_llm.invoke(messages)
    anthropic_review = json.loads(anthropic_response.content)

    # Comparar ambas revisiones
    consensus = openai_review.get("approved") == anthropic_review.get("approved")

    discrepancies = []
    if not consensus:
        discrepancies.append(
            f"OpenAI approved={openai_review.get('approved')}, "
            f"Anthropic approved={anthropic_review.get('approved')}"
        )

    openai_issues = set(openai_review.get("issues", []))
    anthropic_issues = set(anthropic_review.get("issues", []))
    only_openai = openai_issues - anthropic_issues
    only_anthropic = anthropic_issues - openai_issues
    if only_openai:
        discrepancies.append(f"Issues solo OpenAI: {list(only_openai)}")
    if only_anthropic:
        discrepancies.append(f"Issues solo Anthropic: {list(only_anthropic)}")

    recommendation = "approve" if consensus and openai_review.get("approved") else "review_required"

    output = {
        "openai_review": openai_review,
        "anthropic_review": anthropic_review,
        "consensus": consensus,
        "discrepancies": discrepancies,
        "recommendation": recommendation,
    }

    save_agent_result(
        job_id=state["job_id"],
        agent_name="reviewer",
        output=output,
        model_used="gpt-4o+claude-sonnet",
    )

    state["reviewer_output"] = output
    state["current_agent"] = "approval_gate"

    # Si no hay consenso, aprobación humana obligatoria
    if not consensus:
        state["approval_required"] = True
        state["approval_type"] = "review_discrepancy"

    return state
