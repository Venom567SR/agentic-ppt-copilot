"""
ai/agents/manager.py -- (2) classifier + outline planner (Gemini 2.5 Pro) -> HITL gate 2

The LLM returns a PlannerOutput (layouts + titles + kind). The node deterministically
maps each choice to its real template slide via slot_map, drops invalid/duplicate
layouts (logged), and builds a validated DeckPlan. Then it pauses for user approval.
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.manager import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import PlannerOutput, DeckPlan, PlannedSlide
from ai.graph.state import GraphState
from ai.rendering.slot_map import by_id, catalog_for_planner
from ai.src.logger import get_logger
from ai.src.custom_exception import AgentError

logger = get_logger(__name__)


def _format_clarifications(state: GraphState) -> str:
    qs = state.get("clarifying_questions") or []
    ans = state.get("clarification_answers") or {}
    if isinstance(ans, str):
        return f"\n\nUser clarification:\n{ans}"
    if isinstance(ans, dict) and ans:
        pairs = "\n".join(f"Q: {q}\nA: {ans.get(q, '(no answer)')}" for q in qs) if qs \
                else "\n".join(f"Q: {k}\nA: {v}" for k, v in ans.items())
        return f"\n\nUser clarifications:\n{pairs}"
    return ""


class Manager(BaseAgent[PlannerOutput]):
    task = "manager"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = PlannerOutput
    temperature = 0.3

    def build_user_message(self, state: GraphState) -> str:
        msg = f"Topic:\n{state['query']}"
        msg += _format_clarifications(state)
        files = state.get("user_files") or []
        if files:
            msg += f"\n\nThe user attached {len(files)} source document(s); plan slides that can draw on them."
        msg += "\n\nAvailable layouts (choose layout_id only from these):\n"
        msg += catalog_for_planner()
        return msg


_agent = Manager()


def _to_plan(out: PlannerOutput) -> DeckPlan:
    """Map planner choices to a validated DeckPlan: real slides, distinct layouts."""
    seen: set[str] = set()
    planned: list[PlannedSlide] = []
    for ch in out.slides:
        try:
            lay = by_id(ch.layout_id)
        except KeyError:
            logger.warning("[manager] dropping unknown layout_id '%s'", ch.layout_id)
            continue
        if not lay.selectable:
            logger.warning("[manager] dropping non-selectable layout '%s'", ch.layout_id)
            continue
        if ch.layout_id in seen:
            logger.warning("[manager] dropping duplicate layout '%s'", ch.layout_id)
            continue
        seen.add(ch.layout_id)
        planned.append(PlannedSlide(slide=lay.slide, layout_id=ch.layout_id,
                                    title=ch.title, kind=ch.kind))
    if not planned:
        raise AgentError("manager", "planner produced no valid layouts")
    return DeckPlan(deck_title=out.deck_title, slides=planned)


def node(state: GraphState) -> dict:
    """LangGraph node: plan the deck, map to real slides, pause for approval at gate 2."""
    out = _agent.run(state)
    plan = _to_plan(out)
    logger.info("[manager] planned %d slides: %s",
                len(plan.slides), [s.layout_id for s in plan.slides])
    return {"plan": plan, "status": "awaiting_approval"}