"""
nodes/planner.py — Breaks the user query into targeted sub-questions.

The planner is the first node in the graph. It runs once at the start.
Its job: think strategically about what needs to be researched.

Production pattern: Uses structured JSON output (not free-form text).
This means we can validate the output with Pydantic and fail fast
if the LLM gives us garbage instead of silently passing bad data downstream.
"""

import json
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import ResearchState, SubQuestion
from prompts import PLANNER_SYSTEM, PLANNER_HUMAN

logger = logging.getLogger(__name__)


def planner_node(state: ResearchState) -> dict:
    """
    Decomposes the research query into 5-7 targeted sub-questions.

    Input state keys used:  query
    Output state keys set:  sub_questions, status, messages
    """
    query = state["query"]
    logger.info(f"[PLANNER] Planning research for: {query}")
    print(f"\n🗺️  [PLANNER] Breaking down query: '{query}'")

    llm = ChatOpenAI(
        model="gpt-4o-mini",   # Cheaper model — planning doesn't need GPT-4o
        temperature=0,
        response_format={"type": "json_object"},  # Force JSON output
    )

    response = llm.invoke([
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=PLANNER_HUMAN.format(query=query)),
    ])

    # ── Parse and validate JSON output ──────────────────────────────
    try:
        parsed = json.loads(response.content)
        raw_questions = parsed.get("sub_questions", [])
        strategy = parsed.get("research_strategy", "")

        # Validate each sub-question with Pydantic
        sub_questions = []
        for q in raw_questions:
            try:
                validated = SubQuestion(**q)
                sub_questions.append(validated.model_dump())
            except Exception as e:
                logger.warning(f"Skipping invalid sub-question {q}: {e}")

        if not sub_questions:
            # Fallback: create a single sub-question from the original query
            logger.error(f"[PLANNER] LLM returned no valid sub-questions from output: {response.content}. Using fallback.")
            sub_questions = [SubQuestion(
                id="q1",
                question=query,
                focus="general research",
                priority=1,
            ).model_dump()]

    except json.JSONDecodeError as e:
        logger.error(f"[PLANNER] JSON parse failed: {e}. Raw: {response.content[:200]}")
        # Graceful degradation — don't crash, use fallback
        sub_questions = [SubQuestion(
            id="q1", question=query, focus="general research", priority=1
        ).model_dump()]
        strategy = "Fallback: using original query directly"

    # ── Log what was planned ─────────────────────────────────────────
    print(f"✅ [PLANNER] Generated {len(sub_questions)} sub-questions:")
    for sq in sub_questions:
        print(f"   [{sq['id']}] {sq['question']}")
    if strategy:
        print(f"   Strategy: {strategy}")

    return {
        "sub_questions": sub_questions,
        "status": "planning_complete",
        "messages": [AIMessage(content=f"Planned {len(sub_questions)} research directions.")],
    }
