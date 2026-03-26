from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_run_creates_job_and_schedules_graph():
    from main import RunRequest, run

    request = RunRequest(
        job_id="job-123",
        jira_issue="NEXUS-123",
        description="Crear endpoint GET /api/jobs",
        phase="analysis",
    )

    with patch("main.create_job") as mock_create_job, \
         patch("main.update_job_status") as mock_update, \
         patch("main.run_graph", new_callable=AsyncMock) as mock_run_graph, \
         patch("main.asyncio.ensure_future") as mock_ensure_future:

        response = await run(request)

    assert response.job_id == "job-123"
    assert response.status == "running"
    mock_create_job.assert_called_once_with("job-123", "NEXUS-123", trigger_type="analysis")
    mock_update.assert_called_once_with("job-123", "running")
    mock_ensure_future.assert_called_once()
    scheduled_coro = mock_ensure_future.call_args.args[0]
    assert scheduled_coro is not None
    scheduled_coro.close()
    mock_run_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_returns_job_payload():
    from main import status

    with patch(
        "main.get_job_status",
        return_value={"job_id": "job-1", "jira_issue": "NEXUS-1", "status": "running"},
    ):
        result = await status("job-1")

    assert result["job_id"] == "job-1"
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_status_raises_for_unknown_job():
    from main import status

    with patch("main.get_job_status", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await status("missing-job")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approval", "expected_status"),
    [
        ("iterate", "pending"),
        ("rejected", "rejected"),
        ("architecture", "approved"),
        (None, "done"),
    ],
)
async def test_webhook_callback_updates_expected_status(approval: str | None, expected_status: str):
    from main import CallbackPayload, webhook_callback

    payload = CallbackPayload(job_id="job-1", result={}, approval=approval, decided_by="user-1")

    with patch("main.update_job_status") as mock_update:
        result = await webhook_callback(payload)

    assert result == {"received": True, "job_id": "job-1"}
    mock_update.assert_called_once_with("job-1", expected_status)


@pytest.mark.asyncio
async def test_notify_approval_required_posts_to_bot():
    from main import ApprovalNotification, notify_approval_required

    notification = ApprovalNotification(
        job_id="job-1",
        approval_type="visual",
        summary="Revisión final requerida",
    )

    with patch("main.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=MagicMock())

        result = await notify_approval_required(notification)

    assert result == {"status": "notified"}
    mock_client.post.assert_awaited_once()
    assert mock_client.post.call_args.args[0] == "http://nexus-bot:8001/notify"


def test_intake_extract_json_handles_invalid_payload():
    from intake import _extract_json

    assert _extract_json("no es json") == {}
    assert _extract_json("```json\n{invalido}\n```") == {}


@pytest.mark.asyncio
async def test_intake_analyze_request_uses_defaults_when_model_is_sparse():
    from intake import analyze_request

    transcript = [{"role": "user", "content": "Crear endpoint GET /api/jobs"}]

    with patch("intake._run_analysis", return_value={}):
        result = await analyze_request(transcript)

    assert result["ready"] is False
    assert result["refined_issue"].startswith("Crear endpoint GET /api/jobs")
    assert "restricciones" in result["next_question"]
    assert "USER: Crear endpoint GET /api/jobs" in result["refined_description"]


@pytest.mark.asyncio
async def test_intake_analyze_request_preserves_model_answer():
    from intake import analyze_request

    transcript = [{"role": "user", "content": "Necesito listar jobs"}]
    model_payload = {
        "ready": True,
        "next_question": "",
        "missing_details": [],
        "refined_issue": "Historial de jobs",
        "refined_description": "Crear endpoint GET /api/jobs con filtros",
        "summary": "Endpoint de historial paginado",
    }

    with patch("intake._run_analysis", return_value=model_payload):
        result = await analyze_request(transcript)

    assert result["ready"] is True
    assert result["refined_issue"] == "Historial de jobs"
    assert result["summary"] == "Endpoint de historial paginado"


def test_latest_agent_output_parses_json_string():
    from approval_handler import _get_latest_agent_output

    mock_conn = MagicMock()
    mock_cursor_ctx = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('{"consensus": true}',)
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value = mock_cursor_ctx

    with patch("approval_handler.os.getenv", return_value="postgresql://example"), \
         patch("approval_handler.psycopg2.connect", return_value=mock_conn):
        result = _get_latest_agent_output("job-1", "reviewer")

    assert result == {"consensus": True}
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_approval_handler_final_approval_triggers_pr_workflow():
    from approval_handler import approve_job

    job_data = {
        "jira_issue": "NEXUS-200",
        "analyst_output": {
            "original_description": "Crear endpoint GET /api/jobs",
            "scope": "Endpoint de historial",
        },
    }

    with patch("approval_handler.get_job_data", return_value=job_data), \
         patch("approval_handler._get_latest_agent_output", return_value={"consensus": False}), \
         patch("approval_handler.update_job_status") as mock_update, \
         patch("approval_handler.save_decision") as mock_save, \
         patch("approval_handler._notify_n8n") as mock_notify, \
         patch("approval_handler._trigger_pr_workflow") as mock_trigger:

        await approve_job("job-200", "user-2", "architecture")

    assert mock_update.call_count == 2
    assert mock_update.call_args_list[0].args == ("job-200", "approved")
    assert mock_update.call_args_list[1].args == ("job-200", "done")
    mock_save.assert_called_once()
    assert mock_save.call_args.kwargs["decision_type"] == "visual"
    mock_trigger.assert_awaited_once_with("job-200", "NEXUS-200", "Endpoint de historial")
    mock_notify.assert_awaited_once_with("job-200", "visual")


@pytest.mark.asyncio
async def test_reject_job_uses_visual_decision_after_review():
    from approval_handler import reject_job

    with patch("approval_handler._get_latest_agent_output", return_value={"consensus": False}), \
         patch("approval_handler.update_job_status") as mock_update, \
         patch("approval_handler.save_decision") as mock_save, \
         patch("approval_handler._notify_channel") as mock_channel, \
         patch("approval_handler._notify_n8n") as mock_notify:

        await reject_job("job-300", "user-3", "No cumple")

    mock_update.assert_called_once_with("job-300", "rejected")
    assert mock_save.call_args.kwargs["decision_type"] == "visual"
    mock_channel.assert_awaited_once()
    mock_notify.assert_awaited_once_with("job-300", "visual")


def test_db_create_job_inserts_idempotently():
    from db import create_job

    mock_conn = MagicMock()
    mock_cursor_ctx = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value = mock_cursor_ctx

    with patch("db._get_conn", return_value=mock_conn):
        create_job("=job-1", "NEXUS-1", trigger_type="analysis")

    mock_cursor.execute.assert_called_once()
    params = mock_cursor.execute.call_args.args[1]
    assert params == ("job-1", "NEXUS-1", "analysis")
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()
