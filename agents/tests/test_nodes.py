from __future__ import annotations

from unittest.mock import MagicMock, patch

from graph.state import NexusState

BASE_STATE: NexusState = {
    "job_id": "test-job-123",
    "jira_issue": "NEXUS-TEST",
    "description": "Test description",
    "analyst_output": {},
    "developer_output": {},
    "designer_output": {},
    "reviewer_output": {},
    "current_agent": "analyst",
    "status": "running",
    "approval_required": False,
    "approval_type": "",
    "phase": "analysis",
    "error": None,
}


def test_analyst_node():
    with patch("graph.nodes.analyst.ChatOllama") as mock_llm_class, \
         patch("graph.nodes.analyst.save_agent_result") as mock_save, \
         patch("graph.nodes.analyst.httpx.post") as mock_http:

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.content = '{"subtasks": ["task1"], "affected_modules": ["auth"], "complexity": "medium", "scope": "JWT auth"}'
        mock_llm.invoke.return_value = mock_response
        mock_http.return_value = MagicMock(status_code=200)

        from graph.nodes.analyst import analyst_node
        result = analyst_node(BASE_STATE.copy())

        assert result["analyst_output"] != {}
        assert mock_save.called


def test_developer_node():
    with patch("graph.nodes.developer.ChatOllama") as mock_llm_class, \
         patch("graph.nodes.developer.save_agent_result") as mock_save:

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.content = '{"files": ["auth.py"], "tests": ["test_auth.py"], "documentation": "JWT auth docs"}'
        mock_llm.invoke.return_value = mock_response

        from graph.nodes.developer import developer_node
        state = BASE_STATE.copy()
        state["analyst_output"] = {"subtasks": ["Implement JWT"], "affected_modules": ["auth"]}
        result = developer_node(state)

        assert result["developer_output"] != {}
        assert mock_save.called


def test_designer_node():
    with patch("graph.nodes.designer.ChatAnthropic") as mock_llm_class, \
         patch("graph.nodes.designer.save_agent_result") as mock_save:

        mock_llm = MagicMock()
        mock_llm_class.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.content = '{"components": ["LoginForm"], "visual_changes": ["Add JWT badge"], "design_tokens": {}, "interaction_notes": "Token refresh flow"}'
        mock_llm.invoke.return_value = mock_response

        from graph.nodes.designer import designer_node
        state = BASE_STATE.copy()
        state["analyst_output"] = {"subtasks": ["Design login UI"]}
        result = designer_node(state)

        assert result["designer_output"] != {}
        assert mock_save.called


def test_reviewer_node_consensus():
    with patch("graph.nodes.reviewer.ChatOllama") as mock_ollama_class, \
         patch("graph.nodes.reviewer.ChatAnthropic") as mock_anthropic_class, \
         patch("graph.nodes.reviewer.save_agent_result") as mock_save:

        mock_ollama = MagicMock()
        mock_anthropic = MagicMock()
        mock_ollama_class.return_value = mock_ollama
        mock_anthropic_class.return_value = mock_anthropic

        ollama_response = MagicMock()
        ollama_response.content = '{"review": "Good implementation", "issues": [], "approved": true}'
        anthropic_response = MagicMock()
        anthropic_response.content = '{"review": "Solid work", "issues": [], "approved": true}'

        mock_ollama.invoke.return_value = ollama_response
        mock_anthropic.invoke.return_value = anthropic_response

        from graph.nodes.reviewer import reviewer_node
        state = BASE_STATE.copy()
        state["developer_output"] = {"files": ["auth.py"]}
        state["designer_output"] = {"components": ["LoginForm"]}
        result = reviewer_node(state)

        assert result["reviewer_output"] != {}
        assert mock_save.called


def test_reviewer_node_no_consensus():
    with patch("graph.nodes.reviewer.ChatOllama") as mock_ollama_class, \
         patch("graph.nodes.reviewer.ChatAnthropic") as mock_anthropic_class, \
         patch("graph.nodes.reviewer.save_agent_result") as mock_save:

        mock_ollama = MagicMock()
        mock_anthropic = MagicMock()
        mock_ollama_class.return_value = mock_ollama
        mock_anthropic_class.return_value = mock_anthropic

        ollama_response = MagicMock()
        ollama_response.content = '{"review": "Has security issues", "issues": ["SQL injection risk"], "approved": false}'
        anthropic_response = MagicMock()
        anthropic_response.content = '{"review": "Looks good", "issues": [], "approved": true}'

        mock_ollama.invoke.return_value = ollama_response
        mock_anthropic.invoke.return_value = anthropic_response

        from graph.nodes.reviewer import reviewer_node
        state = BASE_STATE.copy()
        state["developer_output"] = {"files": ["auth.py"]}
        state["designer_output"] = {"components": ["LoginForm"]}
        result = reviewer_node(state)

        assert result["approval_required"] is True


def test_extract_json_with_think_tags():
    from graph.nodes.analyst import extract_json

    text = '<think>Let me analyze this</think>\n```json\n{"subtasks": ["task1"], "affected_modules": ["auth"], "complexity": "low", "scope": "test"}\n```'
    result = extract_json(text)
    assert result["subtasks"] == ["task1"]
    assert result["complexity"] == "low"


def test_extract_json_plain():
    from graph.nodes.analyst import extract_json

    text = '{"subtasks": ["task1"], "affected_modules": [], "complexity": "high", "scope": "full"}'
    result = extract_json(text)
    assert result["complexity"] == "high"


def test_nexus_state_structure():
    state = BASE_STATE.copy()
    assert "job_id" in state
    assert "phase" in state
    assert "analyst_output" in state
    assert "reviewer_output" in state
    assert state["approval_required"] is False
