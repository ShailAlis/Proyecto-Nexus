from __future__ import annotations

import base64
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "PN")


def _base_url() -> str:
    return JIRA_URL.rstrip("/")


def get_auth() -> str:
    credentials = f"{JIRA_EMAIL}:{JIRA_TOKEN}"
    return base64.b64encode(credentials.encode()).decode()


def _headers() -> dict:
    return {
        "Authorization": f"Basic {get_auth()}",
        "Content-Type": "application/json",
    }


def _adf_text(text: str) -> dict:
    """Crea un documento ADF simple con un párrafo de texto."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def create_epic(summary: str, description: str) -> dict:
    """Crea una épica en Jira y devuelve {key, id, url}."""
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "issuetype": {"name": "Epic"},
        }
    }
    if description:
        payload["fields"]["description"] = _adf_text(description)

    response = httpx.post(
        f"{_base_url()}/rest/api/3/issue",
        headers=_headers(),
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "key": data["key"],
        "id": data["id"],
        "url": f"{_base_url()}/browse/{data['key']}",
    }


def create_subtask(summary: str, description: str, epic_key: str) -> dict:
    headers = {
        "Authorization": f"Basic {get_auth()}",
        "Content-Type": "application/json"
    }
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "issuetype": {"name": "Task"},
            "parent": {"key": epic_key}
        }
    }
    if description:
        payload["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(description)[:500]}]}]
        }
    response = httpx.post(
        f"{JIRA_URL.rstrip('/')}/rest/api/3/issue",
        headers=headers,
        json=payload
    )
    print(f">>> Jira create_subtask response: {response.status_code} {response.text[:200]}", flush=True)
    response.raise_for_status()
    data = response.json()
    return {
        "key": data["key"],
        "id": data["id"],
        "url": f"{JIRA_URL.rstrip('/')}/browse/{data['key']}"
    }


def post_results_comment(issue_key: str, agent_name: str, model: str, output: dict) -> None:
    """Publica los resultados de un agente como comentario en Jira."""
    headers = {
        "Authorization": f"Basic {get_auth()}",
        "Content-Type": "application/json"
    }

    output_text = []
    for key, value in output.items():
        if isinstance(value, list):
            output_text.append(f"{key}: {', '.join(str(v) for v in value[:5])}")
        elif isinstance(value, dict):
            output_text.append(f"{key}: {str(value)[:200]}")
        else:
            output_text.append(f"{key}: {str(value)[:200]}")

    comment_text = f"Agente {agent_name} ({model}) completó su trabajo:\n\n" + "\n".join(output_text)

    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text[:2000]}]
                }
            ]
        }
    }
    response = httpx.post(
        f"{JIRA_URL.rstrip('/')}/rest/api/3/issue/{issue_key}/comment",
        headers=headers,
        json=payload
    )
    print(f">>> Comentario Jira {issue_key}: {response.status_code}", flush=True)


def add_comment(issue_key: str, comment: str) -> None:
    """Añade un comentario a un issue de Jira."""
    payload = {"body": _adf_text(comment)}
    httpx.post(
        f"{_base_url()}/rest/api/3/issue/{issue_key}/comment",
        headers=_headers(),
        json=payload,
    )


def update_issue_status(issue_key: str, transition_name: str) -> None:
    """Cambia el estado de un issue (To Do -> In Progress -> Done)."""
    headers = _headers()
    # Obtener transiciones disponibles
    resp = httpx.get(
        f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
        headers=headers,
    )
    transitions = resp.json().get("transitions", [])
    transition_id = next(
        (t["id"] for t in transitions if t["name"].lower() == transition_name.lower()),
        None,
    )
    if transition_id:
        httpx.post(
            f"{_base_url()}/rest/api/3/issue/{issue_key}/transitions",
            headers=headers,
            json={"transition": {"id": transition_id}},
        )
