"""
ai/tools/tavily_client.py
=========================
Thin Tavily web-search wrapper. Returns results with source URLs so grounding
flows straight into provenance. Network I/O only -- no LLM here.
"""
from __future__ import annotations

from ai.config_env import settings
from ai.src.logger import get_logger

logger = get_logger(__name__)


def search(query: str, max_results: int = 5) -> list[dict]:
    """Return [{title, url, content}] for a query. Empty list on any failure."""
    if not settings.tavily_api_key:
        logger.warning("TAVILY_API_KEY not set; web search disabled.")
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(query=query, max_results=max_results, search_depth="basic")
        results = resp.get("results", [])
        logger.info("Tavily: %d results for %r", len(results), query[:60])
        return [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "content": r.get("content", "")} for r in results]
    except Exception as e:
        logger.warning("Tavily search failed (%s); proceeding without web evidence.", e)
        return []