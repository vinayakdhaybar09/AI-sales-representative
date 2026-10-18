"""app/graph/builder.py — wires the workflow (matches docs/ARCHITECTURE.md).

START -> session_loader -> query_understanding -> out_of_scope | sufficiency
sufficiency -> clarification | specialist_<intent> -> composer
out_of_scope / clarification / composer -> finalize -> END
(Validator, retry-once and fallback are added in M4.)
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph import routers
from app.graph.nodes.clarification import clarification
from app.graph.nodes.composer import composer
from app.graph.nodes.finalize import finalize
from app.graph.nodes.out_of_scope import out_of_scope
from app.graph.nodes.query_understanding import query_understanding
from app.graph.nodes.session_loader import session_loader
from app.graph.nodes.specialists import (
    specialist_comparison,
    specialist_knowledge,
    specialist_recommendation,
    specialist_support,
)
from app.graph.nodes.sufficiency import sufficiency
from app.graph.state import ChatState

SPECIALISTS = {
    "specialist_recommendation": specialist_recommendation,
    "specialist_comparison": specialist_comparison,
    "specialist_knowledge": specialist_knowledge,
    "specialist_support": specialist_support,
}


@lru_cache
def get_graph():
    """Build and compile the graph once."""
    g = StateGraph(ChatState)
    g.add_node("session_loader", session_loader)
    g.add_node("query_understanding", query_understanding)
    g.add_node("out_of_scope", out_of_scope)
    g.add_node("sufficiency", sufficiency)
    g.add_node("clarification", clarification)
    for name, node in SPECIALISTS.items():
        g.add_node(name, node)
    g.add_node("composer", composer)
    g.add_node("finalize", finalize)

    g.add_edge(START, "session_loader")
    g.add_edge("session_loader", "query_understanding")
    g.add_conditional_edges(
        "query_understanding", routers.after_query_understanding,
        {"out_of_scope": "out_of_scope", "sufficiency": "sufficiency"},
    )
    g.add_conditional_edges(
        "sufficiency", routers.after_sufficiency,
        {"clarification": "clarification", **{name: name for name in SPECIALISTS}},
    )
    for name in SPECIALISTS:
        g.add_edge(name, "composer")
    for name in ("out_of_scope", "clarification", "composer"):
        g.add_edge(name, "finalize")
    g.add_edge("finalize", END)
    return g.compile()
