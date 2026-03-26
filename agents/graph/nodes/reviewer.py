from __future__ import annotations

import json
import logging
import os
import re

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from db import save_agent_result
from graph.state import NexusState

logger = logging.getLogger("nexus.reviewer")

REVIEW_PROMPT = """Eres un revisor experto del sistema NEXUS. Analiza los outputs del desarrollador y disenador.

Evalua:
- Calidad y correccion del codigo propuesto
- Coherencia entre codigo y especificacion de diseno
- Posibles problemas de seguridad, rendimiento o mantenibilidad
- Alineacion con los requisitos originales del analista

Responde en JSON valido:
{
  "score": 0-100,
  "issues": ["..."],
  "suggestions": ["..."],
  "approved": true/false
}"""


def _build_context(state: NexusState) -> str:
    return (
        f"Issue Jira: {state['jira_issue']}\n\n"
        f"Descripcion original:\n{state['description']}\n\n"
        f"Output del Analista:\n{json.dumps(state['analyst_output'], ensure_ascii=False)}\n\n"
        f"Output del Desarrollador:\n{json.dumps(state['developer_output'], ensure_ascii=False)}\n\n"
        f"Output del Disenador:\n{json.dumps(state['designer_output'], ensure_ascii=False)}"
    )


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return {"score": 0, "issues": [], "suggestions": [], "approved": False}


def reviewer_node(state: NexusState) -> NexusState:
    print(f">>> [REVIEWER] Iniciando para job {state['job_id']}", flush=True)
    print(">>> [REVIEWER] Llamando a deepseek-r1:14b...", flush=True)

    context = _build_context(state)
    messages = [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": context},
    ]

    ollama_llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.1,
        base_url="http://ollama:11434",
    )
    ollama_response = ollama_llm.invoke(messages)
    ollama_review = _extract_json(ollama_response.content)

    print(">>> [REVIEWER] Llamando a claude-sonnet...", flush=True)
    anthropic_llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.1,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    anthropic_response = anthropic_llm.invoke(messages)
    anthropic_review = _extract_json(anthropic_response.content)

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
    state["current_agent"] = "awaiting_approval"
    state["approval_required"] = True
    state["approval_type"] = "visual"

    try:
        if not consensus:
            summary = (
                "Revision humana requerida por discrepancias entre modelos.\n\n"
                f"Problemas detectados:\n"
                f"{chr(10).join(str(item) for item in output.get('discrepancies', [])[:3]) or 'Sin detalles adicionales'}"
            )
        else:
            summary = (
                "Revision final lista para decision humana.\n\n"
                f"Recomendacion automatica: {output.get('recommendation', 'review_required')}\n"
                f"Score DeepSeek: {ollama_review.get('score', 'N/A')}\n"
                f"Score Claude: {anthropic_review.get('score', 'N/A')}"
            )

        httpx.post(
            "http://agents:8000/notify/approval-required",
            json={
                "job_id": state["job_id"],
                "approval_type": "visual",
                "summary": summary[:1500],
            },
            timeout=10,
        )
    except Exception:
        logger.exception("No se pudo solicitar aprobacion humana para job %s", state["job_id"])

    print(f">>> [REVIEWER] Completado - consenso: {output.get('consensus')}", flush=True)
    return state
