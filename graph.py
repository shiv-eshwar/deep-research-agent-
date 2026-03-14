"""
graph.py — Assembles the complete deep research graph.

This is where all nodes and edges come together into a runnable graph.

The graph has TWO loops:
  Loop 1 (Research): searcher → reflector → searcher (if gaps found)
  Loop 2 (Writing):  writer → critic → writer (if revision needed)

Visual:
  START
    │
    ▼
  planner
    │
    ▼
  searcher ◄──────────────────────┐
    │                             │
    ▼                             │ (needs_more_research)
  reflector ──────────────────────┘
    │
    │ (sufficient)
    ▼
  writer ◄────────────────────────┐
    │                             │
    ▼                             │ (needs_revision)
  critic ──────────────────────────┘
    │
    │ (approved)
    ▼
   END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from state import ResearchState, MIN_COVERAGE_TO_WRITE, MAX_RESEARCH_ITERATIONS, MAX_REVISIONS
from nodes import (
    planner_node,
    searcher_node,
    reflector_node,
    writer_node,
    critic_node,
)


# ══════════════════════════════════════════════════════════════════
# ROUTING FUNCTIONS
# These read state and return the name of the next node.
# They are attached to nodes as conditional edges.
# ══════════════════════════════════════════════════════════════════

def route_after_reflection(state: ResearchState) -> str:
    """
    After reflector runs: do we have enough research, or search more?

    Returns "writer" if sufficient, "searcher" if more research needed.
    """
    reflection = state.get("reflection", {})
    iterations = state.get("research_iterations", 0)

    # Force proceed if we've hit the cap
    if iterations >= MAX_RESEARCH_ITERATIONS:
        print("   → Routing: reflector → writer (max iterations)")
        return "writer"

    is_sufficient = reflection.get("is_sufficient", False)
    coverage = reflection.get("coverage_score", 0.0)

    if is_sufficient and coverage >= MIN_COVERAGE_TO_WRITE:
        print(f"   → Routing: reflector → writer (coverage: {coverage:.0%})")
        return "writer"
    else:
        print(f"   → Routing: reflector → searcher (coverage: {coverage:.0%}, needs more)")
        return "searcher"


def route_after_critique(state: ResearchState) -> str:
    """
    After critic runs: is the report approved, or does it need revision?

    Returns END if approved, "writer" if revision needed.
    """
    critique = state.get("critique", {})
    revision_count = state.get("revision_count", 0)
    final_report = state.get("final_report", "")

    # If final_report was set, the critic approved it
    if final_report:
        print("   → Routing: critic → END (approved)")
        return END

    # Force finish if revision cap hit
    if revision_count >= MAX_REVISIONS:
        print(f"   → Routing: critic → END (max revisions)")
        return END

    approved = critique.get("approved", False)
    quality = critique.get("quality_score", 0.0)

    if approved or quality >= 0.7:
        print(f"   → Routing: critic → END (quality: {quality:.0%})")
        return END
    else:
        print(f"   → Routing: critic → writer (quality: {quality:.0%}, needs revision)")
        return "writer"


# ══════════════════════════════════════════════════════════════════
# GRAPH BUILDER
# ══════════════════════════════════════════════════════════════════

def build_graph(use_memory: bool = True):
    """
    Builds and compiles the deep research StateGraph.

    Args:
        use_memory: If True, attaches MemorySaver for checkpointing.
                   Set to False for stateless API calls.

    Returns:
        Compiled LangGraph ready to .invoke() or .stream()
    """
    builder = StateGraph(ResearchState)

    # ── Add all nodes ────────────────────────────────────────────────
    builder.add_node("planner",   planner_node)
    builder.add_node("searcher",  searcher_node)
    builder.add_node("reflector", reflector_node)
    builder.add_node("writer",    writer_node)
    builder.add_node("critic",    critic_node)

    # ── Set entry point ──────────────────────────────────────────────
    builder.add_edge(START, "planner")

    # ── Fixed edges ──────────────────────────────────────────────────
    # planner always goes to searcher
    builder.add_edge("planner", "searcher")
    # searcher always goes to reflector
    builder.add_edge("searcher", "reflector")
    # writer always goes to critic
    builder.add_edge("writer", "critic")

    # ── Conditional edges (the loops) ────────────────────────────────
    # After reflection: go to writer OR loop back to searcher
    builder.add_conditional_edges(
        "reflector",
        route_after_reflection,
        {
            "writer":   "writer",
            "searcher": "searcher",
        }
    )

    # After critique: go to END OR loop back to writer
    builder.add_conditional_edges(
        "critic",
        route_after_critique,
        {
            "writer": "writer",
            END:       END,
        }
    )

    # ── Checkpointing ────────────────────────────────────────────────
    checkpointer = MemorySaver() if use_memory else None

    # ── Compile ──────────────────────────────────────────────────────
    graph = builder.compile(checkpointer=checkpointer)

    return graph


# ── Quick test: visualize the graph ─────────────────────────────────
if __name__ == "__main__":
    graph = build_graph(use_memory=False)
    print("\n📊 Graph structure:")
    print(graph.get_graph().draw_ascii())
    print("\n✅ Graph compiled successfully.")
