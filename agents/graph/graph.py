from __future__ import annotations

from langgraph.graph import END, StateGraph

from db import update_job_status
from graph.nodes.analyst import analyst_node
from graph.nodes.designer import designer_node
from graph.nodes.developer import developer_node
from graph.nodes.reviewer import reviewer_node
from graph.state import NexusState


def approval_gate(state: NexusState) -> NexusState:
    """Pausa el grafo si se requiere aprobación humana."""
    if state["approval_required"]:
        update_job_status(state["job_id"], "awaiting_approval")
        state["status"] = "awaiting_approval"
    else:
        update_job_status(state["job_id"], "done")
        state["status"] = "done"
    return state


def route_after_reviewer(state: NexusState) -> str:
    return "approval_gate"


def route_after_approval(state: NexusState) -> str:
    return END


def build_graph() -> StateGraph:
    graph = StateGraph(NexusState)

    # Nodos
    graph.add_node("analyst", analyst_node)
    graph.add_node("developer", developer_node)
    graph.add_node("designer", designer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("approval_gate", approval_gate)

    # Flujo: analyst → developer + designer en paralelo → reviewer → approval_gate
    graph.set_entry_point("analyst")

    # Después del analyst, lanzamos developer y designer
    # LangGraph ejecuta nodos sin dependencias entre sí en paralelo
    graph.add_edge("analyst", "developer")
    graph.add_edge("analyst", "designer")

    # Ambos convergen en reviewer
    graph.add_edge("developer", "reviewer")
    graph.add_edge("designer", "reviewer")

    # Reviewer → approval_gate → END
    graph.add_conditional_edges("reviewer", route_after_reviewer)
    graph.add_conditional_edges("approval_gate", route_after_approval)

    return graph


# Grafo compilado listo para ejecución
workflow = build_graph().compile()


def run_graph(initial_state: NexusState) -> NexusState:
    """Ejecuta el grafo completo. Se llama desde un BackgroundTask."""
    try:
        result = workflow.invoke(initial_state)
        return result
    except Exception as e:
        update_job_status(initial_state["job_id"], "done")
        initial_state["status"] = "error"
        initial_state["error"] = str(e)
        return initial_state
