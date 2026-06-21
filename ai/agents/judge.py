"""
ai/agents/judge.py -- (4) grounding guardrail (Gemini 2.5 Pro)

Verifies each DATA slide's claims against the evidence gathered for it. Generic by
design: it checks against whatever evidence is supplied (web now, user files once
context_retriever lands) and honours Source authority (user_file > web > none).
v1 verifies and reports; the repair/degradation routing is wired at the graph level.
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.judge import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import GuardrailResult, SlideContent
from ai.graph.state import GraphState
from ai.src.logger import get_logger

logger = get_logger(__name__)


def _slide_text_blob(sc: SlideContent) -> str:
    parts = [" ".join(v.lines) for v in sc.text.values()]
    if sc.table:
        parts += [" | ".join(r) for r in sc.table]
    if sc.smartart:
        parts.append(" / ".join(sc.smartart))
    return "\n".join(p for p in parts if p.strip())


class Judge(BaseAgent[GuardrailResult]):
    task = "judge"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = GuardrailResult
    temperature = 0.0                       # deterministic verification

    def build_user_message(self, state: GraphState) -> str:
        sc: SlideContent = state["_slide_content"]
        evidence = state.get("_evidence") or "(no external evidence was gathered)"
        return (f"SLIDE CONTENT:\n{_slide_text_blob(sc)}\n\n"
                f"EVIDENCE:\n{evidence}\n\nVerify the slide's claims against the evidence.")


_agent = Judge()


def check_one(slide_content: SlideContent, evidence: str, query: str) -> GuardrailResult:
    return _agent.run({"_slide_content": slide_content, "_evidence": evidence, "query": query})


def node(state: GraphState) -> dict:
    """LangGraph node: verify every data slide; report unsupported claims.

    Evidence = curated user-file ground truth (whole-deck, authoritative) + any
    per-slide web evidence. Combining both means the judge always sees the user's
    uploaded data and won't flag file-sourced figures as unsupported."""
    from ai.agents.deck_writer import _combine_evidence
    slides: list[SlideContent] = state["slides"]
    plan = state["plan"]
    kind_by_slide = {p.slide: p.kind for p in plan.slides}
    evidence_by_slide = state.get("evidence_by_slide", {})
    curated = state.get("curated_evidence", "")

    results: dict[int, GuardrailResult] = {}
    for sc in slides:
        if kind_by_slide.get(sc.slide) != "data":
            continue
        evidence = _combine_evidence(curated, evidence_by_slide.get(sc.slide, ""))
        result = check_one(sc, evidence, state["query"])
        results[sc.slide] = result
        if not result.passed:
            bad = [c.claim for c in result.checks if not c.supported]
            logger.warning("[judge] slide %s: %d unsupported claim(s): %s",
                           sc.slide, len(bad), bad[:3])
        else:
            logger.info("[judge] slide %s: all %d claim(s) grounded", sc.slide, len(result.checks))

    return {"guardrail": results}