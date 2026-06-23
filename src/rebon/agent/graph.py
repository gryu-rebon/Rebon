from langgraph.graph import StateGraph, END
from .state import AgentState


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    # TODO: add nodes
    return graph.compile()
