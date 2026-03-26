from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_ollama import ChatOllama

INTAKE_SYSTEM_PROMPT = """Eres el analista funcional y tecnico de NEXUS.
Tu trabajo es aclarar una petición de desarrollo antes de lanzar el flujo multiagente.

Debes decidir si ya hay suficiente información para empezar a implementar o si falta contexto.

Responde SIEMPRE y SOLO con JSON válido con esta estructura:
{
  "ready": true,
  "next_question": "",
  "missing_details": ["..."],
  "refined_issue": "titulo corto y claro",
  "refined_description": "descripcion tecnica completa y fiel a lo pedido por el usuario",
  "summary": "resumen corto de lo que se va a construir"
}

Reglas:
- "ready" debe ser true solo si ya se puede implementar con suficiente claridad.
- Si "ready" es false, "next_question" debe contener una unica pregunta concreta y util.
- No inventes frameworks ni tecnologias no mencionadas en la conversacion.
- Conserva el lenguaje del usuario.
- "refined_issue" debe ser una frase corta, util como titulo interno del job.
- "refined_description" debe incorporar la petición original y las aclaraciones del hilo.
- Evita preguntas innecesarias; pregunta solo lo que sea imprescindible para reducir ambigüedad."""


def _extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}
    return {}


def _format_transcript(transcript: list[dict[str, str]]) -> str:
    lines = []
    for item in transcript:
        role = item.get("role", "user").upper()
        content = item.get("content", "").strip()
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _run_analysis(transcript: list[dict[str, str]]) -> dict[str, Any]:
    llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.1,
        base_url="http://ollama:11434",
    )
    messages = [
        {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Analiza esta conversación de descubrimiento y decide si ya se puede arrancar el job.\n\n"
                f"{_format_transcript(transcript)}"
            ),
        },
    ]
    response = llm.invoke(messages)
    return _extract_json(response.content if hasattr(response, "content") else str(response))


async def analyze_request(transcript: list[dict[str, str]]) -> dict[str, Any]:
    parsed = await asyncio.to_thread(_run_analysis, transcript)

    ready = bool(parsed.get("ready"))
    next_question = str(parsed.get("next_question") or "").strip()
    missing_details = parsed.get("missing_details")
    if not isinstance(missing_details, list):
        missing_details = []

    refined_issue = str(parsed.get("refined_issue") or "").strip()
    refined_description = str(parsed.get("refined_description") or "").strip()
    summary = str(parsed.get("summary") or "").strip()

    if not refined_issue:
        first_user_message = next(
            (item.get("content", "").strip() for item in transcript if item.get("role") == "user"),
            "Nueva tarea NEXUS",
        )
        refined_issue = first_user_message[:80]

    if not refined_description:
        refined_description = _format_transcript(transcript)

    if not summary:
        summary = refined_issue[:200]

    if not ready and not next_question:
        next_question = (
            "¿Qué resultado exacto esperas y qué restricciones funcionales o técnicas "
            "debemos respetar?"
        )

    return {
        "ready": ready,
        "next_question": next_question,
        "missing_details": missing_details[:5],
        "refined_issue": refined_issue[:120],
        "refined_description": refined_description[:4000],
        "summary": summary[:500],
    }
