"""
tools.py — External tools for the research agent.

Production principle: ABSTRACT YOUR TOOLS BEHIND A CLEAN INTERFACE.
The nodes don't care if you're using Tavily, DuckDuckGo, or a custom API.
They just call search(query) and get back structured results.

This file provides:
  1. search_web()    — main search function (Tavily with DuckDuckGo fallback)
  2. scrape_url()    — fetch full content from a URL
  3. SearchOutput    — typed return value so nodes get consistent data
"""

import os
import re
import time
import logging
import requests
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# TYPED OUTPUT — nodes always get consistent structure back
# ══════════════════════════════════════════════════════════════════

class WebSearchResult(BaseModel):
    """A single search result returned by search_web()."""
    title: str
    url: str
    content: str       # Snippet or scraped content
    score: float = 0.5 # Relevance score if available


class SearchOutput(BaseModel):
    """Complete output from a search_web() call."""
    query: str
    results: list[WebSearchResult]
    source: str  # "tavily" or "duckduckgo"
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════
# SEARCH — Tavily first, DuckDuckGo fallback
# ══════════════════════════════════════════════════════════════════

def search_web(query: str, max_results: int = 5) -> SearchOutput:
    """
    Search the web for a query. Returns structured results.

    Tries Tavily first (better quality, requires API key).
    Falls back to DuckDuckGo if Tavily key not available.
    Production systems should always have a fallback.
    """
    tavily_key = os.getenv("TAVILY_API_KEY")

    if tavily_key:
        return _search_tavily(query, max_results, tavily_key)
    else:
        logger.warning("No TAVILY_API_KEY found. Falling back to DuckDuckGo.")
        return _search_duckduckgo(query, max_results)


def _search_tavily(query: str, max_results: int, api_key: str) -> SearchOutput:
    """
    Search using Tavily API.
    Tavily is purpose-built for AI research agents — returns clean content,
    not raw HTML. This is why it's the recommended choice for production.
    """
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)

        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",   # Deep search mode
            include_answer=False,      # We want raw results, not pre-synthesized
            include_raw_content=True,  # Get full content, not just snippets
        )

        results = []
        for r in response.get("results", []):
            content = r.get("raw_content") or r.get("content", "")
            results.append(WebSearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=content[:3000],  # Cap to 3000 chars to manage tokens
                score=r.get("score", 0.5),
            ))

        logger.info(f"Tavily: found {len(results)} results for '{query}'")
        return SearchOutput(query=query, results=results, source="tavily")

    except Exception as e:
        logger.error(f"Tavily search failed: {e}. Falling back to DuckDuckGo.")
        return _search_duckduckgo(query, max_results)


def _search_duckduckgo(query: str, max_results: int) -> SearchOutput:
    """
    Search using DuckDuckGo — free, no API key required.
    Includes retry logic to handle rate limits.
    """
    try:
        from duckduckgo_search import DDGS
        import duckduckgo_search.exceptions

        results = []
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append(WebSearchResult(
                            title=r.get("title", ""),
                            url=r.get("href", ""),
                            content=r.get("body", "")[:3000],
                            score=0.5,
                        ))
                break  # Success, exit retry loop
            except duckduckgo_search.exceptions.DuckDuckGoSearchException as e:
                if "202 Ratelimit" in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, ...
                    logger.warning(f"DuckDuckGo rate limit hit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise  # Re-raise if not a rate limit or out of retries

        logger.info(f"DuckDuckGo: found {len(results)} results for '{query}'")
        return SearchOutput(query=query, results=results, source="duckduckgo")

    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return SearchOutput(
            query=query, results=[], source="duckduckgo",
            error=str(e)
        )


# ══════════════════════════════════════════════════════════════════
# SCRAPER — Fetch full content from a specific URL
# ══════════════════════════════════════════════════════════════════

def scrape_url(url: str, max_chars: int = 4000) -> str:
    """
    Fetches and cleans text content from a URL.
    Returns cleaned text truncated to max_chars.

    Used when search results give a URL and we need the full article content.
    Production tip: For heavy scraping, use Playwright or Firecrawl instead.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Strip HTML tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', response.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        truncated = text[:max_chars]
        logger.info(f"Scraped {len(truncated)} chars from {url}")
        return truncated

    except requests.exceptions.Timeout:
        logger.warning(f"Scrape timeout for {url}")
        return f"[Scrape timeout for {url}]"
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error {e.response.status_code} for {url}")
        return f"[HTTP error {e.response.status_code} for {url}]"
    except Exception as e:
        logger.error(f"Scrape failed for {url}: {e}")
        return f"[Scrape failed: {str(e)}]"


# ══════════════════════════════════════════════════════════════════
# HELPER — Format search results for LLM consumption
# ══════════════════════════════════════════════════════════════════

def format_results_for_llm(search_output: SearchOutput) -> str:
    """
    Converts SearchOutput into a clean string the LLM can process.
    Numbered, with URL and content clearly labeled.
    """
    if search_output.error:
        return f"Search failed: {search_output.error}"

    if not search_output.results:
        return f"No results found for: {search_output.query}"

    lines = [f"Search results for: '{search_output.query}'\n"]
    for i, r in enumerate(search_output.results, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    URL: {r.url}")
        lines.append(f"    Content: {r.content}")
        lines.append("")

    return "\n".join(lines)
