"""
nodes/searcher.py — Executes web searches and builds the knowledge base.

The searcher runs in a loop. On first run it searches the planned sub-questions.
On subsequent runs (after reflector finds gaps) it searches follow-up queries.

Production patterns used here:
  - Rate limiting between searches (respect APIs, avoid bans)
  - Deduplication (don't store the same URL twice)
  - Knowledge base synthesis (don't just dump raw text — structure it)
  - Token budget management (cap content length to control LLM costs)
"""

import logging
import time
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import ResearchState, SearchResult
from tools import search_web, format_results_for_llm
from prompts import SYNTHESIZER_SYSTEM, SYNTHESIZER_HUMAN

logger = logging.getLogger(__name__)

SEARCH_DELAY_SECONDS = 0.5  # Polite delay between searches


def searcher_node(state: ResearchState) -> dict:
    """
    Searches the web for all pending sub-questions and follow-up queries.
    Synthesizes results into an updated knowledge base.

    Input state keys used:  sub_questions, follow_up_queries, search_results,
                            knowledge_base, query, research_iterations
    Output state keys set:  search_results, knowledge_base, status,
                            research_iterations, sub_questions, messages
    """
    query = state["query"]
    existing_results = state.get("search_results", [])
    existing_kb = state.get("knowledge_base", "")
    sub_questions = state.get("sub_questions", [])
    follow_ups = state.get("follow_up_queries", [])
    iteration = state.get("research_iterations", 0)

    print(f"\n🔍 [SEARCHER] Search iteration {iteration + 1}")

    # ── Build the list of queries to run this iteration ─────────────
    queries_to_search: list[tuple[str, str]] = []  # (sub_question_id, query_string)

    # On first run: search all un-searched sub-questions
    if iteration == 0:
        for sq in sub_questions:
            if not sq.get("searched", False):
                queries_to_search.append((sq["id"], sq["question"]))
    else:
        # On follow-up runs: search the reflector's gap queries
        for fq in follow_ups:
            queries_to_search.append(("followup", fq))

    if not queries_to_search:
        logger.warning("[SEARCHER] No queries to search.")
        return {"status": "searching_complete", "research_iterations": iteration + 1}

    print(f"   Running {len(queries_to_search)} searches...")

    # ── Execute searches ─────────────────────────────────────────────
    new_results: list[dict] = []
    seen_urls = {r["source_url"] for r in existing_results}  # Deduplication set

    for sq_id, search_query in queries_to_search:
        print(f"   🔎 Searching: '{search_query[:70]}'")
        search_output = search_web(search_query, max_results=4)

        for web_result in search_output.results:
            # Skip duplicates
            if web_result.url in seen_urls:
                continue
            seen_urls.add(web_result.url)

            result = SearchResult(
                sub_question_id=sq_id,
                query_used=search_query,
                source_url=web_result.url,
                source_title=web_result.title,
                content=web_result.content,
                relevance_score=web_result.score,
            )
            new_results.append(result.model_dump())

        # Mark sub-question as searched
        for sq in sub_questions:
            if sq["id"] == sq_id:
                sq["searched"] = True

        time.sleep(SEARCH_DELAY_SECONDS)  # Rate limiting

    all_results = existing_results + new_results
    print(f"✅ [SEARCHER] Collected {len(new_results)} new sources "
          f"({len(all_results)} total)")

    # ── Synthesize into knowledge base ───────────────────────────────
    # Don't just dump raw results — structure them into a knowledge base
    # the LLM can use efficiently. This saves tokens and improves quality.
    print("   📚 Synthesizing knowledge base...")

    formatted_new = "\n\n".join([
        f"Source: {r['source_title']}\nURL: {r['source_url']}\n{r['content']}"
        for r in new_results[:12]  # Cap at 12 sources to manage context window
    ])

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    synthesis_response = llm.invoke([
        SystemMessage(content=SYNTHESIZER_SYSTEM),
        HumanMessage(content=SYNTHESIZER_HUMAN.format(
            query=query,
            search_results=formatted_new,
            existing_knowledge=existing_kb[:3000] if existing_kb else "None yet.",
        )),
    ])

    updated_kb = synthesis_response.content

    return {
        "search_results": all_results,
        "knowledge_base": updated_kb,
        "sub_questions": sub_questions,
        "research_iterations": iteration + 1,
        "follow_up_queries": [],   # Clear after using them
        "status": "searching_complete",
        "messages": [AIMessage(
            content=f"Search iteration {iteration + 1} complete. "
                    f"Found {len(new_results)} new sources."
        )],
    }
