from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import END, StateGraph

from db import update_job_status
from graph.nodes.analyst import analyst_node
from graph.nodes.designer import designer_node
from graph.nodes.developer import developer_node
from graph.nodes.reviewer import reviewer_node
from graph.state import NexusState


def analysis_gate(state: NexusState) -> NexusState:
    update_job_status(state["job_id"], "awaiting_approval")
    state["current_agent"] = "awaiting_approval"
    state["status"] = "awaiting_approval"
    return state


def review_gate(state: NexusState) -> NexusState:
    if state["approval_required"]:
        update_job_status(state["job_id"], "awaiting_approval")
        state["current_agent"] = "awaiting_approval"
        state["status"] = "awaiting_approval"
    else:
        update_job_status(state["job_id"], "done")
        state["current_agent"] = "done"
        state["status"] = "done"
    return state


def build_analysis_graph() -> StateGraph:
    graph = StateGraph(NexusState)
    graph.add_node("analyst", analyst_node)
    graph.add_node("analysis_gate", analysis_gate)
    graph.set_entry_point("analyst")
    graph.add_edge("analyst", "analysis_gate")
    graph.add_edge("analysis_gate", END)
    return graph


def build_development_graph() -> StateGraph:
    graph = StateGraph(NexusState)
    graph.add_node("developer", developer_node)
    graph.add_node("designer", designer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("review_gate", review_gate)
    graph.add_node("fork", lambda state: state)
    graph.set_entry_point("fork")
    graph.add_edge("fork", "developer")
    graph.add_edge("fork", "designer")
    graph.add_edge("developer", "reviewer")
    graph.add_edge("designer", "reviewer")
    graph.add_edge("reviewer", "review_gate")
    graph.add_edge("review_gate", END)
    return graph


def build_review_graph() -> StateGraph:
    graph = StateGraph(NexusState)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("review_gate", review_gate)
    graph.set_entry_point("reviewer")
    graph.add_edge("reviewer", "review_gate")
    graph.add_edge("review_gate", END)
    return graph


_graphs = {
    "analysis": build_analysis_graph().compile(),
    "development": build_development_graph().compile(),
    "review": build_review_graph().compile(),
}

_executor = ThreadPoolExecutor(max_workers=4)


def _run_graph_sync(initial_state: NexusState) -> NexusState:
    try:
        phase = initial_state.get("phase", "analysis")
        print(f">>> _run_graph_sync iniciado para job {initial_state['job_id']} (phase={phase})")
        workflow = _graphs[phase]
        result = workflow.invoke(initial_state)
        print(f">>> workflow.invoke completado para job {initial_state['job_id']}")
        return result
    except Exception as e:
        print(f">>> ERROR en workflow.invoke: {e}")
        import traceback

        traceback.print_exc()
        update_job_status(initial_state["job_id"], "rejected")
        initial_state["current_agent"] = "error"
        initial_state["status"] = "error"
        initial_state["error"] = str(e)
        return initial_state


async def run_graph(initial_state: NexusState) -> NexusState:
    print(f">>> run_graph async llamado para job {initial_state['job_id']}")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _run_graph_sync, initial_state)
    return result
