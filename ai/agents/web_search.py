"""
ai/agents/web_search.py -- (3) grounding agent (Gemini 2.5 Flash) + Tavily tool

A proper BaseAgent: the LLM formulates focused search queries from the slide
context (consistent with every other agent); the Tavily tool then executes them.
gather() returns (evidence_text, sources) for deck_writer to ground a data slide.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ai.agents.base import BaseAgent
from ai.agents_prompts.web_search import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import SearchQueries, Source
from ai.tools.tavily_client import search
from ai.src.logger import get_logger

logger = get_logger(__name__)


class WebSearch(BaseAgent[SearchQueries]):
    task = "web_search"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = SearchQueries
    temperature = 0.3

    def build_user_message(self, state) -> str:
        return (f"Presentation topic: {state['_search_topic']}\n"
                f"Slide title: {state['_search_title']}\n\n"
                f"Produce 1-3 web search queries to find current, factual data for this slide.")


_agent = WebSearch()


def gather(topic: str, slide_title: str, per_query: int = 4, cap: int = 6) -> tuple[str, list[Source]]:
    """Plan queries (LLM) -> execute (Tavily) -> (evidence_text, deduped sources)."""
    try:
        queries = _agent.run({"_search_topic": topic, "_search_title": slide_title}).queries
    except Exception as e:
        logger.warning("[web_search] query planning failed (%s); using fallback query", e)
        queries = [f"{topic} {slide_title} India latest data statistics"]

    results, seen = [], set()
    for q in queries:
        for r in search(q, max_results=per_query):
            if r["url"] and r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)
    results = results[:cap]
    if not results:
        return "", []

    now = datetime.now(timezone.utc)
    sources = [Source(url=r["url"], title=r["title"] or r["url"],
                      retrieved_at=now, authority="web") for r in results]
    evidence = "\n\n".join(f"[{r['title']}] {r['url']}\n{r['content'][:600]}" for r in results)
    logger.info("[web_search] '%s' -> %d queries, %d sources", slide_title, len(queries), len(sources))
    return evidence, sources