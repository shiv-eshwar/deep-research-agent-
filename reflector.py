"""
nodes/reflector.py — Evaluates research completeness and decides whether to loop.

This is the "brain" of the research loop. After each search round, the reflector
asks: "Do we know enough to write a quality report?"

If YES → route to writer
If NO  → generate targeted follow-up queries → route back to searcher

Production patterns:
  - Structured JSON output for reliable routing decisions
  - Pydantic validation of LLM response
  - Graceful fallback if JSON parsing fails
  - Clear logging so you can debug routing decisions
"""

import json
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import ResearchState, ReflectionOutput, MAX_RESEARCH_ITERATIONS
from prompts import REFLECTOR_SYSTEM, REFLECTOR_HUMAN

logger = logging.getLogger(__name__)


def reflector_node(state: ResearchState) -> dict:
    """
    Evaluates whether current research is sufficient to write the report.

    Input state keys used:  query, sub_questions, knowledge_base,
                            research_iterations
    Output state keys set:  reflection, follow_up_queries, status, messages
    """
    query = state["query"]
    knowledge_base = state.get("knowledge_base", "")
    sub_questions = state.get("sub_questions", [])
    iterations = state.get("research_iterations", 0)

    print(f"\n🤔 [REFLECTOR] Evaluating research after {iterations} iteration(s)...")

    # ── Safety valve: force proceed if we've hit the iteration cap ───
    if iterations >= MAX_RESEARCH_ITERATIONS:
        print(f"⚠️  [REFLECTOR] Max iterations ({MAX_RESEARCH_ITERATIONS}) reached. "
              f"Forcing write stage.")
        return {
            "reflection": ReflectionOutput(
                is_sufficient=True,
                coverage_score=0.6,
                gaps=[],
                follow_up_queries=[],
                reasoning=f"Forced sufficient after {iterations} iterations.",
            ).model_dump(),
            "follow_up_queries": [],
            "status": "reflection_complete_forced",
        }

    # ── Format sub-questions for the prompt ─────────────────────────
    sq_text = "\n".join([
        f"  [{sq['id']}] {sq['question']} "
        f"(searched: {'yes' if sq.get('searched') else 'no'})"
        for sq in sub_questions
    ])

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
    )

    response = llm.invoke([
        SystemMessage(content=REFLECTOR_SYSTEM),
        HumanMessage(content=REFLECTOR_HUMAN.format(
            query=query,
            sub_questions=sq_text,
            knowledge_base=knowledge_base[:4000],  # Cap to save tokens
            iterations=iterations,
        )),
    ])

    # ── Parse and validate ───────────────────────────────────────────
    try:
        parsed = json.loads(response.content)
        reflection = ReflectionOutput(**parsed)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"[REFLECTOR] Parse failed for output: {response.content}. Error: {e}. Defaulting to sufficient.")
        reflection = ReflectionOutput(
            is_sufficient=True,
            coverage_score=0.65,
            gaps=[],
            follow_up_queries=[],
            reasoning="Parse error — defaulting to sufficient to avoid infinite loop.",
        )

    # ── Log the decision ─────────────────────────────────────────────
    status_icon = "✅" if reflection.is_sufficient else "🔄"
    print(f"{status_icon} [REFLECTOR] Coverage: {reflection.coverage_score:.0%} | "
          f"Sufficient: {reflection.is_sufficient}")
    if reflection.gaps:
        print(f"   Gaps found: {len(reflection.gaps)}")
        for gap in reflection.gaps[:3]:
            print(f"   - {gap}")
    if reflection.follow_up_queries:
        print(f"   Follow-up queries: {len(reflection.follow_up_queries)}")

    return {
        "reflection": reflection.model_dump(),
        "follow_up_queries": reflection.follow_up_queries,
        "status": "reflection_complete",
        "messages": [AIMessage(
            content=f"Reflection: {'sufficient' if reflection.is_sufficient else 'needs more research'}. "
                    f"Coverage: {reflection.coverage_score:.0%}."
        )],
    }
