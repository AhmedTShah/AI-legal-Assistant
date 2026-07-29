"""
graph.py — LegalMind Pipeline Orchestration Engine
===================================================
Pure Python Stateful StateGraph Engine for LegalMind.
Implements the exact LangGraph API structure (StateGraph, add_node,
add_edge, add_conditional_edges, compile, invoke) without triggering
Windows Security DLL / AppLocker blocks (_xxhash.pyd).

Connected Active Nodes:
1. intent_router_node (Node 1)
2. web_search_node    (External Branch Node)

Conditional Edges:
- route_by_intent:
    "external_search"   -> web_search_node
    "internal_pipeline" -> query_decomposer_node
"""

import sys
from pathlib import Path
from typing import Dict, Any, Callable, List, Optional, Tuple, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Agents.state import LegalMindState
from Agents.intent_router import intent_router_node, route_by_intent
from Agents.web_search_agent import web_search_node
from Agents.query_decomposer import query_decomposer_node
from Agents.statute_agent import statute_agent_node
from Agents.case_law_agent import case_law_agent_node
from Agents.synthesis_agent import synthesis_agent_node

START = "__START__"
END = "__END__"


# ──────────────────────────────────────────────────────────────
# PURE PYTHON STATEGRAPH ENGINE (Windows DLL Safe)
# ──────────────────────────────────────────────────────────────

class StateGraphEngine:
    """
    Pure Python implementation of LangGraph's StateGraph API.
    Zero external C-DLL dependencies. 100% Windows Security / AppLocker safe.
    """
    def __init__(self, state_schema):
        self.state_schema = state_schema
        self.nodes: Dict[str, Callable] = {}
        self.edges: Dict[str, str] = {}
        self.conditional_edges: Dict[str, Tuple[Callable, Dict[str, str]]] = {}
        self.entry_point: Optional[str] = None

    def add_node(self, name: str, func: Callable):
        self.nodes[name] = func

    def add_edge(self, source: str, target: str):
        if source == START:
            self.entry_point = target
        else:
            self.edges[source] = target

    def add_conditional_edges(self, source: str, router_func: Callable, path_map: Dict[str, str]):
        if source == START:
            raise ValueError("START node cannot have conditional edges directly. Use add_edge(START, node_name).")
        self.conditional_edges[source] = (router_func, path_map)

    def compile(self):
        return CompiledGraphApp(self)


class CompiledGraphApp:
    """
    Compiled executable pipeline graph app.
    Provides the standard app.invoke(initial_state) method.
    """
    def __init__(self, graph_engine: StateGraphEngine):
        self.nodes = graph_engine.nodes
        self.edges = graph_engine.edges
        self.conditional_edges = graph_engine.conditional_edges
        self.entry_point = graph_engine.entry_point

    def invoke(self, initial_state: LegalMindState) -> LegalMindState:
        """
        Executes the graph sequentially and conditionally updating state.
        """
        current_state = dict(initial_state)
        current_node = self.entry_point

        if not current_node:
            raise ValueError("Graph has no entry point defined! Use add_edge(START, node_name).")

        visited_count = 0
        max_steps = 25  # Safety loop guard

        while current_node and current_node != END and visited_count < max_steps:
            visited_count += 1
            if current_node not in self.nodes:
                raise ValueError(f"Node '{current_node}' not found in registered nodes!")

            # 1. Execute current node function
            node_func = self.nodes[current_node]
            updated_payload = node_func(current_state)

            # 2. Update state dictionary
            if isinstance(updated_payload, dict):
                for k, v in updated_payload.items():
                    if k in ("web_search_results", "retrieved_chunks", "verified_citations", "sub_queries", "urdu_terms_found"):
                        # Handle list append semantics
                        existing = current_state.get(k, []) or []
                        if isinstance(v, list):
                            current_state[k] = list(existing) + list(v)
                        else:
                            current_state[k] = list(existing) + [v]
                    else:
                        current_state[k] = v

            # 3. Determine next node (Conditional Edge or Fixed Edge)
            if current_node in self.conditional_edges:
                router_func, path_map = self.conditional_edges[current_node]
                route_key = router_func(current_state)
                if route_key not in path_map:
                    raise ValueError(f"Route key '{route_key}' not found in path_map {path_map}")
                current_node = path_map[route_key]
            elif current_node in self.edges:
                current_node = self.edges[current_node]
            else:
                break

        return current_state


# Try importing native LangGraph first, fallback seamlessly to PurePythonStateGraph if DLL blocked
try:
    from langgraph.graph import StateGraph, START, END
except Exception:
    StateGraph = StateGraphEngine




# ──────────────────────────────────────────────────────────────
# GRAPH CONSTRUCTION
# ──────────────────────────────────────────────────────────────

def build_legalmind_graph():
    """
    Constructs and compiles the LangGraph StateGraph pipeline.
    
    Returns:
        Compiled LangGraph Application (app)
    """
    builder = StateGraph(LegalMindState)

    # 1. Add Active Specialist & Synthesizer Nodes
    builder.add_node("intent_router", intent_router_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("query_decomposer", query_decomposer_node)
    builder.add_node("statute_agent", statute_agent_node)
    builder.add_node("case_law_agent", case_law_agent_node)
    builder.add_node("synthesis_agent", synthesis_agent_node)

    # 2. Add Entry Point Edge (START -> intent_router)
    builder.add_edge(START, "intent_router")

    # 3. Add Conditional Edge after intent_router
    builder.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "external_search": "web_search",
            "internal_pipeline": "query_decomposer"
        }
    )

    # 4. Sequential Specialist Pipelines to Synthesis
    builder.add_edge("query_decomposer", "statute_agent")
    builder.add_edge("statute_agent", "case_law_agent")
    builder.add_edge("case_law_agent", "synthesis_agent")

    # 5. Terminal Edges to END
    builder.add_edge("web_search", END)
    builder.add_edge("synthesis_agent", END)

    # 6. Compile Graph
    app = builder.compile()
    return app


# Create compiled instance for easy import
app = build_legalmind_graph()

