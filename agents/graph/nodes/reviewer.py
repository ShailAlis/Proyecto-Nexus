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
    print(f">>> [REVIEWER] Iniciando para job {state['job_id']}", flush=True)
    print(f">>> [REVIEWER] Llamando a deepseek-r1:14b...", flush=True)

    context = _build_context(state)

    messages = [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": context},
    ]

    # Revision con Ollama (DeepSeek)
    ollama_llm = ChatOllama(
        model="deepseek-r1:14b",
        temperature=0.1,
        base_url="http://ollama:11434",
    )

    def extract_json(text: str) -> dict:
        # Elimina bloques <think>...</think> de deepseek-r1
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Busca bloque ```json ... ```
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Busca JSON directo { ... }
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Devuelve estructura por defecto si no encuentra JSON
        return {
            "score": 0,
            "issues": [],
            "suggestions": [],
            "approved": False,
        }

    ollama_response = ollama_llm.invoke(messages)
    ollama_review = extract_json(ollama_response.content)

    # Revision con Anthropic (Claude)
    print(f">>> [REVIEWER] Llamando a claude-sonnet...", flush=True)
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

    # Si hay consenso positivo -> commit a GitHub
    consensus = output.get("consensus", False)
    pr_url = None

    if consensus:
        try:
            from github_client import create_branch, commit_files, create_pull_request
            from db import get_job_data

            branch_name = f"nexus/{state['job_id'][:8]}"
            job_data = get_job_data(state["job_id"])

            print(f">>> [REVIEWER] Consenso positivo - creando rama {branch_name}", flush=True)
            create_branch(branch_name)

            # Preparar archivos del developer output
            dev_output = state.get("developer_output", {})
            files_to_commit = []

            raw_files = dev_output.get("files", [])
            if isinstance(raw_files, list):
                for i, f in enumerate(raw_files):
                    if isinstance(f, dict) and "path" in f and "content" in f:
                        files_to_commit.append(f)
                    elif isinstance(f, str):
                        files_to_commit.append(
                            {
                                "path": f"nexus-generated/{state['job_id'][:8]}/file_{i}.py",
                                "content": f,
                            }
                        )

            # Si no hay archivos estructurados, guardar el output completo
            if not files_to_commit:
                files_to_commit.append(
                    {
                        "path": f"nexus-generated/{state['job_id'][:8]}/output.md",
                        "content": (
                            f"# NEXUS Generated Output\n\nJob: {state['job_id']}\n"
                            f"Issue: {state['jira_issue']}\n\n## Developer Output\n\n"
                            f"{str(dev_output)[:5000]}"
                        ),
                    }
                )

            commit_message = (
                f"feat(nexus): {state['jira_issue'][:60]}\n\n"
                f"Generated by NEXUS agents\nJob: {state['job_id']}"
            )

            committed = commit_files(branch_name, files_to_commit, commit_message)

            if committed:
                pr = create_pull_request(
                    branch_name=branch_name,
                    title=f"[NEXUS] {state['jira_issue'][:60]}",
                    body=(
                        f"## Generado automaticamente por NEXUS\n\n"
                        f"**Job ID:** {state['job_id']}\n"
                        f"**Jira:** {state.get('analyst_output', {}).get('jira_epic_key', 'N/A')}\n\n"
                        f"## Resumen del Revisor\n\n"
                        f"{str(output.get('recommendation', ''))[:1000]}\n\n"
                        f"---\nRevision requerida antes de mergear"
                    ),
                )
                pr_url = pr.get("url")
                print(f">>> [REVIEWER] PR creado: {pr_url}", flush=True)

            _ = job_data
        except Exception as e:
            print(f">>> ERROR en commit GitHub: {e}", flush=True)
            import traceback

            traceback.print_exc()
    else:
        print(f">>> [REVIEWER] Discrepancias detectadas - requiere aprobación humana", flush=True)
        try:
            import httpx as _httpx
            discrepancies_summary = str(output.get("discrepancies", []))[:500]
            _httpx.post(
                "http://nexus-bot:8001/notify",
                json={
                    "job_id": state["job_id"],
                    "approval_type": "security",
                    "summary": f"⚠️ Discrepancias entre modelos detectadas. Revisión humana requerida.\n\nProblemas: {discrepancies_summary}"
                },
                timeout=10.0
            )
            print(f">>> [REVIEWER] Solicitud de aprobación enviada a Discord", flush=True)
        except Exception as e:
            print(f">>> ERROR enviando aprobación revisor: {e}", flush=True)

    try:
        from db import get_job_epic_key
        from jira_client import post_results_comment, update_issue_status

        epic_key = get_job_epic_key(state["job_id"])

        if epic_key:
            # Comentario en Jira con resumen del revisor
            post_results_comment(epic_key, "Revisor/QA", "deepseek-r1:14b+claude-sonnet", output)
            print(f">>> Resultados QA publicados en Jira {epic_key}", flush=True)

        # Notificacion Discord con enlace al PR si existe
        discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
        if discord_webhook:
            emoji = "✅" if consensus else "⚠️"
            fields = [
                {"name": "Job ID", "value": state["job_id"][:8] + "...", "inline": True},
                {"name": "Consenso QA", "value": "✅ Sí" if consensus else "⚠️ Discrepancias", "inline": True},
                {"name": "Modelos", "value": "deepseek+claude+qwen", "inline": True},
            ]
            if not consensus:
                discrepancies_summary = "\n".join(str(item) for item in output.get("discrepancies", [])[:3])
                if discrepancies_summary:
                    fields.append(
                        {
                            "name": "Explicación",
                            "value": discrepancies_summary[:1000],
                            "inline": False,
                        }
                    )
            if pr_url:
                fields.append({"name": "Pull Request", "value": pr_url, "inline": False})

            message = {
                "embeds": [
                    {
                        "title": f"{emoji} NEXUS - Job completado",
                        "color": 5763719 if consensus else 16776960,
                        "fields": fields,
                    }
                ]
            }
            try:
                import httpx as _httpx

                _httpx.post(discord_webhook, json=message)
                print(f">>> [REVIEWER] Notificación Discord enviada", flush=True)
            except Exception as e:
                print(f">>> ERROR Discord webhook: {e}", flush=True)

        _ = update_issue_status
    except Exception as e:
        print(f">>> Error en notificaciones finales: {e}", flush=True)

    state["reviewer_output"] = output
    state["current_agent"] = "approval_gate"

    # Si no hay consenso, aprobacion humana obligatoria
    if not consensus:
        state["approval_required"] = True
        state["approval_type"] = "review_discrepancy"

    print(f">>> [REVIEWER] Completado - consenso: {output.get('consensus')}", flush=True)
    return state
