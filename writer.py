"""
nodes/writer.py — Writes the research report from the knowledge base.

The writer uses gpt-4o (not mini) because report quality is the final product.
It handles both first drafts and revisions (when the critic sends it back).

Production patterns:
  - Uses gpt-4o for quality where it matters most
  - Handles the revision case differently from the first draft
  - Saves output to file immediately (don't trust in-memory state alone)
  - Logs word count so you can tell if the report is too short
"""

import os
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import ResearchState
from prompts import (
    WRITER_SYSTEM, WRITER_HUMAN,
    WRITER_REVISION_INSTRUCTION
)

logger = logging.getLogger(__name__)


def writer_node(state: ResearchState) -> dict:
    """
    Writes or revises the research report.

    First run: writes a fresh draft from the knowledge base.
    Subsequent runs: revises the draft based on critic feedback.

    Input state keys used:  query, knowledge_base, draft_report,
                            critique, revision_count
    Output state keys set:  draft_report, revision_count, status, messages
    """
    query = state["query"]
    knowledge_base = state.get("knowledge_base", "")
    existing_draft = state.get("draft_report", "")
    critique = state.get("critique", {})
    revision_count = state.get("revision_count", 0)

    is_revision = revision_count > 0 and existing_draft and critique

    print(f"\n✍️  [WRITER] {'Revising draft' if is_revision else 'Writing first draft'}...")

    # ── Build revision instruction if revising ───────────────────────
    if is_revision:
        weaknesses = critique.get("weaknesses", [])
        revisions = critique.get("specific_revisions", [])
        critique_points = "\n".join(
            [f"- {w}" for w in weaknesses] +
            [f"- MUST FIX: {r}" for r in revisions]
        )
        revision_instruction = WRITER_REVISION_INSTRUCTION.format(
            critique_points=critique_points,
            previous_draft=existing_draft[:2000],
        )
        print(f"   Addressing {len(weaknesses)} weaknesses and "
              f"{len(revisions)} required revisions")
    else:
        revision_instruction = ""

    # ── Use gpt-4o for writing (quality matters here) ────────────────
    llm = ChatOpenAI(
        model="gpt-4o",   # Full model for writing quality
        temperature=0.3,  # Slight creativity for natural writing
    )

    response = llm.invoke([
        SystemMessage(content=WRITER_SYSTEM),
        HumanMessage(content=WRITER_HUMAN.format(
            query=query,
            knowledge_base=knowledge_base,
            revision_instruction=revision_instruction,
        )),
    ])

    draft = response.content
    word_count = len(draft.split())

    # ── Save draft to disk ───────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    draft_path = f"output/draft_v{revision_count + 1}.md"
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(draft)

    print(f"✅ [WRITER] Draft written: {word_count} words → saved to {draft_path}")

    return {
        "draft_report": draft,
        "revision_count": revision_count + 1,
        "status": f"draft_v{revision_count + 1}_complete",
        "messages": [AIMessage(
            content=f"Draft {'revision ' + str(revision_count) if is_revision else ''} "
                    f"written: {word_count} words."
        )],
    }
