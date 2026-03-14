"""
state.py — The single source of truth for the entire research graph.

Production principle: DEFINE YOUR STATE BEFORE YOU WRITE A SINGLE NODE.
Your state is your API contract between all agents. Getting it right
upfront saves you from refactoring everything later.

This file defines:
  1. Pydantic models for structured data (SearchResult, SubQuestion, etc.)
  2. ResearchState — the main TypedDict that flows through the graph
  3. Factory functions to create clean initial states
"""

from __future__ import annotations
from typing import TypedDict, Annotated, Literal
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


# ══════════════════════════════════════════════════════════════════
# PYDANTIC MODELS — Structured data inside the state
# Using Pydantic forces structure — no more messy unvalidated strings
# ══════════════════════════════════════════════════════════════════

class SubQuestion(BaseModel):
    """A targeted sub-question derived from the main research query."""
    id: str = Field(description="Unique ID like 'q1', 'q2'")
    question: str = Field(description="The specific sub-question to research")
    focus: str = Field(description="What aspect this question targets")
    priority: int = Field(description="1=highest priority, 5=lowest", ge=1, le=5)
    searched: bool = Field(default=False, description="Has this been searched yet?")


class SearchResult(BaseModel):
    """A single search result with content and metadata."""
    sub_question_id: str = Field(description="Which sub-question this answers")
    query_used: str = Field(description="The exact search query that was run")
    source_url: str = Field(description="URL of the source")
    source_title: str = Field(description="Title of the page/article")
    content: str = Field(description="Extracted text content (truncated)")
    relevance_score: float = Field(
        description="How relevant this is (0.0 - 1.0)",
        ge=0.0, le=1.0, default=0.5
    )


class ReflectionOutput(BaseModel):
    """Structured output from the reflector node."""
    is_sufficient: bool = Field(
        description="True if we have enough research to write a quality report"
    )
    coverage_score: float = Field(
        description="How well the sub-questions are covered (0.0 - 1.0)",
        ge=0.0, le=1.0
    )
    gaps: list[str] = Field(
        description="List of specific gaps or unanswered questions",
        default_factory=list
    )
    follow_up_queries: list[str] = Field(
        description="Specific search queries to fill the gaps",
        default_factory=list
    )
    reasoning: str = Field(description="Why this decision was made")


class CritiqueOutput(BaseModel):
    """Structured output from the critic node."""
    approved: bool = Field(description="True if the report is good enough to publish")
    quality_score: float = Field(
        description="Overall quality score (0.0 - 1.0)",
        ge=0.0, le=1.0
    )
    strengths: list[str] = Field(description="What the report does well")
    weaknesses: list[str] = Field(description="What needs improvement")
    specific_revisions: list[str] = Field(
        description="Exact changes the writer should make",
        default_factory=list
    )
    reasoning: str = Field(description="Overall assessment")


# ══════════════════════════════════════════════════════════════════
# MAIN STATE — The shared whiteboard all nodes read and write
# ══════════════════════════════════════════════════════════════════

class ResearchState(TypedDict):
    """
    The complete state of a deep research job.

    Every node receives this full state.
    Every node returns ONLY the keys it changed.
    LangGraph merges partial updates back into this state automatically.

    Fields are grouped by lifecycle stage:
      INPUT → PLANNING → RESEARCH → REFLECTION → WRITING → OUTPUT
    """

    # ── INPUT ───────────────────────────────────────────────────────
    query: str
    # The original user query — never modified after initialization

    # ── PLANNING ────────────────────────────────────────────────────
    sub_questions: list[dict]
    # List of SubQuestion dicts (serialized Pydantic models)
    # Set by: planner_node
    # Read by: searcher_node (to know what to search)

    # ── RESEARCH ────────────────────────────────────────────────────
    search_results: list[dict]
    # Accumulated SearchResult dicts from all search iterations
    # Set by: searcher_node (appends each run)
    # Read by: reflector_node, writer_node

    knowledge_base: str
    # Synthesized, deduplicated facts from all search results
    # Set by: searcher_node after each search round
    # Read by: reflector_node, writer_node

    # ── REFLECTION ──────────────────────────────────────────────────
    reflection: dict
    # ReflectionOutput dict from the reflector
    # Set by: reflector_node
    # Read by: graph routing (is_sufficient → determines if we loop)

    follow_up_queries: list[str]
    # Additional search queries from reflection gaps
    # Set by: reflector_node
    # Read by: searcher_node on follow-up iterations

    # ── WRITING ─────────────────────────────────────────────────────
    draft_report: str
    # Current draft from writer_node
    # Set by: writer_node
    # Read by: critic_node

    critique: dict
    # CritiqueOutput dict from critic_node
    # Set by: critic_node
    # Read by: graph routing (approved → determines if we loop)

    # ── OUTPUT ──────────────────────────────────────────────────────
    final_report: str
    # The approved, finished report in Markdown
    # Set by: writer_node after critic approval

    # ── METADATA ────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]
    # Full conversation/event log — appended to (never overwritten)
    # The `Annotated[list, add_messages]` reducer auto-appends

    research_iterations: int
    # How many search → reflect loops have run
    # Safety valve: caps at MAX_RESEARCH_ITERATIONS

    revision_count: int
    # How many write → critique loops have run
    # Safety valve: caps at MAX_REVISIONS

    status: str
    # Human-readable status for streaming/API responses
    # e.g. "planning", "searching", "reflecting", "writing", "done"


# ══════════════════════════════════════════════════════════════════
# CONSTANTS — Tune these to control agent behavior and cost
# ══════════════════════════════════════════════════════════════════

MAX_RESEARCH_ITERATIONS = 3   # Max search → reflect loops before forcing write
MAX_REVISIONS = 2             # Max write → critique loops before forcing finish
MIN_COVERAGE_TO_WRITE = 0.6  # Reflector must score ≥ 0.6 to proceed to writing
MIN_QUALITY_TO_PUBLISH = 0.7 # Critic must score ≥ 0.7 to approve the report


# ══════════════════════════════════════════════════════════════════
# FACTORY — Always use this to create initial state
# ══════════════════════════════════════════════════════════════════

def create_initial_state(query: str) -> ResearchState:
    """Creates a clean ResearchState for a new research job."""
    return ResearchState(
        query=query,
        sub_questions=[],
        search_results=[],
        knowledge_base="",
        reflection={},
        follow_up_queries=[],
        draft_report="",
        critique={},
        final_report="",
        messages=[],
        research_iterations=0,
        revision_count=0,
        status="initialized",
    )
