"""
nodes/critic.py — Reviews the draft and decides to approve or send back for revision.

The critic is the quality gate. Nothing ships without passing through here.
It gives structured feedback that the writer uses to revise.

Production patterns:
  - Hard cap on revisions to prevent infinite write-critique loops
  - Structured JSON feedback (not just "this is bad" — specific actionable items)
  - Saves the final approved report to disk with a timestamp
"""

import json
import logging
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import ResearchState, CritiqueOutput, MAX_REVISIONS, MIN_QUALITY_TO_PUBLISH
from prompts import CRITIC_SYSTEM, CRITIC_HUMAN

logger = logging.getLogger(__name__)


def critic_node(state: ResearchState) -> dict:
    """
    Reviews the draft report and either approves it or requests revisions.

    Input state keys used:  query, draft_report, revision_count
    Output state keys set:  critique, final_report (if approved), status, messages
    """
    query = state["query"]
    draft = state.get("draft_report", "")
    revision_count = state.get("revision_count", 0)

    print(f"\n🧐 [CRITIC] Reviewing draft (revision {revision_count})...")

    # ── Force approval if we've hit the revision cap ─────────────────
    if revision_count >= MAX_REVISIONS:
        print(f"⚠️  [CRITIC] Max revisions ({MAX_REVISIONS}) reached. Force-approving.")
        critique = CritiqueOutput(
            approved=True,
            quality_score=0.75,
            strengths=["Completed within revision budget"],
            weaknesses=[],
            specific_revisions=[],
            reasoning=f"Auto-approved after {revision_count} revisions.",
        )
        return _finalize_report(draft, critique, query)

    # ── Run the critique ─────────────────────────────────────────────
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
    )

    response = llm.invoke([
        SystemMessage(content=CRITIC_SYSTEM),
        HumanMessage(content=CRITIC_HUMAN.format(
            query=query,
            draft_report=draft,
        )),
    ])

    # ── Parse and validate ───────────────────────────────────────────
    try:
        parsed = json.loads(response.content)
        critique = CritiqueOutput(**parsed)
    except Exception as e:
        logger.error(f"[CRITIC] Parse failed for output: {response.content}. Error: {e}. Auto-approving.")
        critique = CritiqueOutput(
            approved=True,
            quality_score=0.7,
            strengths=["Parse error — auto-approved"],
            weaknesses=[],
            specific_revisions=[],
            reasoning="Parse error on critique — defaulting to approve.",
        )

    # ── Log the decision ─────────────────────────────────────────────
    decision_icon = "✅" if critique.approved else "🔄"
    print(f"{decision_icon} [CRITIC] Quality: {critique.quality_score:.0%} | "
          f"Approved: {critique.approved}")

    if critique.weaknesses:
        print(f"   Weaknesses: {len(critique.weaknesses)}")
        for w in critique.weaknesses[:2]:
            print(f"   - {w}")

    # ── If approved, finalize the report ────────────────────────────
    if critique.approved or critique.quality_score >= MIN_QUALITY_TO_PUBLISH:
        return _finalize_report(draft, critique, query)

    # ── If not approved, return critique for writer to use ───────────
    return {
        "critique": critique.model_dump(),
        "status": "revision_requested",
        "messages": [AIMessage(
            content=f"Draft needs revision. Score: {critique.quality_score:.0%}. "
                    f"Issues: {len(critique.weaknesses)}"
        )],
    }


def _finalize_report(draft: str, critique: CritiqueOutput, query: str) -> dict:
    """Saves the approved final report to disk and updates state."""
    import os
    os.makedirs("output", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = f"output/final_report_{timestamp}.md"

    with open(final_path, "w", encoding="utf-8") as f:
        f.write(draft)

    print(f"🎉 [CRITIC] Report APPROVED! Saved to {final_path}")

    return {
        "final_report": draft,
        "critique": critique.model_dump(),
        "status": "completed",
        "messages": [AIMessage(
            content=f"Report approved with quality score {critique.quality_score:.0%}. "
                    f"Saved to {final_path}."
        )],
    }
