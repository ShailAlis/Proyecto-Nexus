from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from graph.state import NexusState


def _base_state() -> NexusState:
    return {
        "job_id": "test-job-001",
        "jira_issue": "NEXUS-42",
        "description": "Añadir endpoint de búsqueda avanzada con filtros",
        "analyst_output": {},
        "developer_output": {},
        "designer_output": {},
        "reviewer_output": {},
        "current_agent": "analyst",
        "status": "running",
        "approval_required": False,
        "approval_type": "",
        "error": None,
    }


ANALYST_RESPONSE = json.dumps({
    "subtasks": ["Crear schema de filtros", "Implementar endpoint GET /search"],
    "affected_modules": ["api", "database"],
    "complexity": "medium",
    "scope": "Nuevo endpoint de búsqueda con filtros dinámicos",
})

DEVELOPER_RESPONSE = json.dumps({
    "files": [{"path": "api/search.py", "language": "python", "content": "# search endpoint"}],
    "tests": [{"path": "tests/test_search.py", "description": "Test search", "content": "..."}],
    "documentation": "Endpoint de búsqueda añadido.",
})

DESIGNER_RESPONSE = json.dumps({
    "components": ["SearchBar", "FilterPanel"],
    "visual_changes": ["Añadir panel de filtros lateral"],
    "design_tokens": {"colors": {}, "typography": {}, "spacing": {}},
    "interaction_notes": "Filtros colapsables en móvil",
})

REVIEW_RESPONSE = json.dumps({
    "score": 85,
    "issues": [],
    "suggestions": ["Añadir paginación"],
    "approved": True,
})


@patch("graph.nodes.analyst.save_agent_result")
@patch("graph.nodes.analyst.ChatOpenAI")
def test_analyst_node(mock_openai_cls, mock_save):
    from graph.nodes.analyst import analyst_node

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=ANALYST_RESPONSE)
    mock_openai_cls.return_value = mock_llm

    state = _base_state()
    result = analyst_node(state)

    assert result["analyst_output"]["complexity"] == "medium"
    assert len(result["analyst_output"]["subtasks"]) == 2
    mock_save.assert_called_once()


@patch("graph.nodes.developer.save_agent_result")
@patch("graph.nodes.developer.ChatOpenAI")
def test_developer_node(mock_openai_cls, mock_save):
    from graph.nodes.developer import developer_node

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=DEVELOPER_RESPONSE)
    mock_openai_cls.return_value = mock_llm

    state = _base_state()
    state["analyst_output"] = json.loads(ANALYST_RESPONSE)
    result = developer_node(state)

    assert len(result["developer_output"]["files"]) == 1
    mock_save.assert_called_once()


@patch("graph.nodes.designer.save_agent_result")
@patch("graph.nodes.designer.ChatOpenAI")
def test_designer_node(mock_openai_cls, mock_save):
    from graph.nodes.designer import designer_node

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=DESIGNER_RESPONSE)
    mock_openai_cls.return_value = mock_llm

    state = _base_state()
    state["analyst_output"] = json.loads(ANALYST_RESPONSE)
    result = designer_node(state)

    assert "SearchBar" in result["designer_output"]["components"]
    mock_save.assert_called_once()


@patch("graph.nodes.reviewer.save_agent_result")
@patch("graph.nodes.reviewer.ChatAnthropic")
@patch("graph.nodes.reviewer.ChatOpenAI")
def test_reviewer_node_consensus(mock_openai_cls, mock_anthropic_cls, mock_save):
    from graph.nodes.reviewer import reviewer_node

    mock_openai = MagicMock()
    mock_openai.invoke.return_value = MagicMock(content=REVIEW_RESPONSE)
    mock_openai_cls.return_value = mock_openai

    mock_anthropic = MagicMock()
    mock_anthropic.invoke.return_value = MagicMock(content=REVIEW_RESPONSE)
    mock_anthropic_cls.return_value = mock_anthropic

    state = _base_state()
    state["analyst_output"] = json.loads(ANALYST_RESPONSE)
    state["developer_output"] = json.loads(DEVELOPER_RESPONSE)
    state["designer_output"] = json.loads(DESIGNER_RESPONSE)

    result = reviewer_node(state)

    assert result["reviewer_output"]["consensus"] is True
    assert result["approval_required"] is False
    mock_save.assert_called_once()


@patch("graph.nodes.reviewer.save_agent_result")
@patch("graph.nodes.reviewer.ChatAnthropic")
@patch("graph.nodes.reviewer.ChatOpenAI")
def test_reviewer_node_no_consensus(mock_openai_cls, mock_anthropic_cls, mock_save):
    from graph.nodes.reviewer import reviewer_node

    rejected_review = json.dumps({
        "score": 40,
        "issues": ["Falta validación de inputs"],
        "suggestions": ["Añadir validación"],
        "approved": False,
    })

    mock_openai = MagicMock()
    mock_openai.invoke.return_value = MagicMock(content=REVIEW_RESPONSE)
    mock_openai_cls.return_value = mock_openai

    mock_anthropic = MagicMock()
    mock_anthropic.invoke.return_value = MagicMock(content=rejected_review)
    mock_anthropic_cls.return_value = mock_anthropic

    state = _base_state()
    state["analyst_output"] = json.loads(ANALYST_RESPONSE)
    state["developer_output"] = json.loads(DEVELOPER_RESPONSE)
    state["designer_output"] = json.loads(DESIGNER_RESPONSE)

    result = reviewer_node(state)

    assert result["reviewer_output"]["consensus"] is False
    assert result["approval_required"] is True
    assert result["approval_type"] == "review_discrepancy"


@patch("graph.graph.update_job_status")
@patch("graph.nodes.reviewer.save_agent_result")
@patch("graph.nodes.reviewer.ChatAnthropic")
@patch("graph.nodes.reviewer.ChatOpenAI")
@patch("graph.nodes.designer.save_agent_result")
@patch("graph.nodes.designer.ChatOpenAI")
@patch("graph.nodes.developer.save_agent_result")
@patch("graph.nodes.developer.ChatOpenAI")
@patch("graph.nodes.analyst.save_agent_result")
@patch("graph.nodes.analyst.ChatOpenAI")
def test_full_graph_happy_path(
    mock_analyst_openai_cls,
    mock_analyst_save,
    mock_dev_openai_cls,
    mock_dev_save,
    mock_design_openai_cls,
    mock_design_save,
    mock_rev_openai_cls,
    mock_rev_anthropic_cls,
    mock_rev_save,
    mock_update_status,
):
    from graph.graph import run_graph

    # Analyst
    mock_analyst = MagicMock()
    mock_analyst.invoke.return_value = MagicMock(content=ANALYST_RESPONSE)
    mock_analyst_openai_cls.return_value = mock_analyst

    # Developer
    mock_dev = MagicMock()
    mock_dev.invoke.return_value = MagicMock(content=DEVELOPER_RESPONSE)
    mock_dev_openai_cls.return_value = mock_dev

    # Designer
    mock_design = MagicMock()
    mock_design.invoke.return_value = MagicMock(content=DESIGNER_RESPONSE)
    mock_design_openai_cls.return_value = mock_design

    # Reviewer (ambos LLMs)
    mock_rev_openai = MagicMock()
    mock_rev_openai.invoke.return_value = MagicMock(content=REVIEW_RESPONSE)
    mock_rev_openai_cls.return_value = mock_rev_openai

    mock_rev_anthropic = MagicMock()
    mock_rev_anthropic.invoke.return_value = MagicMock(content=REVIEW_RESPONSE)
    mock_rev_anthropic_cls.return_value = mock_rev_anthropic

    state = _base_state()
    result = run_graph(state)

    assert result["status"] == "done"
    assert result["reviewer_output"]["consensus"] is True
