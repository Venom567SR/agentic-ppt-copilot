"""
ai/agents/deck_writer.py -- (3) per-slot content reasoner (Gemini 2.5 Pro)

Per-slide: turns one PlannedSlide into a SlideContent that fits the layout's
capacities and flows straight into the renderer. The node loops the approved
plan, fit-validates each slide, and does ONE tightening retry on overflow.
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.deck_writer import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import SlideDraft, SlideContent, SlotContent, PlannedSlide
from ai.graph.state import GraphState
from ai.rendering.slot_map import by_id, writer_brief
from ai.rendering import fit_validator as fv
from ai.src.logger import get_logger

logger = get_logger(__name__)


class DeckWriter(BaseAgent[SlideDraft]):
    task = "deck_writer"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = SlideDraft
    temperature = 0.4

    def build_user_message(self, state: GraphState) -> str:
        planned: PlannedSlide = state["_slide"]
        plan = state["plan"]
        layout = by_id(planned.layout_id)
        titles = ", ".join(s.title for s in plan.slides)
        msg = (f"Presentation: {plan.deck_title}\n"
               f"Topic: {state['query']}\n"
               f"All slide titles (for coherence): {titles}\n\n"
               f"Write content for THIS slide.\n"
               f"Slide title: {planned.title}\n"
               f"Kind: {planned.kind}\n\n"
               f"{writer_brief(layout)}")
        if state.get("_tighten"):
            msg += f"\n\nIMPORTANT: {state['_tighten']}"
        return msg


_agent = DeckWriter()


def _draft_to_content(planned: PlannedSlide, draft: SlideDraft) -> SlideContent:
    text = {s.role: SlotContent(lines=list(s.lines)) for s in draft.slots}
    table = [list(r.cells) for r in draft.table_rows] if draft.table_rows else None
    return SlideContent(slide=planned.slide, layout_id=planned.layout_id,
                        text=text, table=table, smartart=draft.smartart)


def _validate(draft: SlideDraft, layout) -> list:
    vios = []
    for s in draft.slots:
        ts = fv.slot_by_role(layout, s.role)
        if ts is None:
            vios.append(fv.Violation(s.role, "unknown_slot", f"role '{s.role}' not in layout"))
            continue
        vios += fv.check_text(s.role, ts, s.lines)
    if layout.table and draft.table_rows:
        vios += fv.check_table([list(r.cells) for r in draft.table_rows], layout)
    if layout.smartart and draft.smartart is not None:
        vios += fv.check_smartart(draft.smartart, layout)
    return vios


def write_one(state: GraphState, planned: PlannedSlide) -> SlideContent:
    layout = by_id(planned.layout_id)
    draft = _agent.run({**state, "_slide": planned})
    vios = _validate(draft, layout)
    if vios:
        hint = ("Some content did not fit. Fix these and keep everything within limits: "
                + "; ".join(v.detail for v in vios[:4]))
        logger.warning("[deck_writer] slide %s (%s) fit issues, one retry: %s",
                       planned.slide, planned.layout_id, [v.kind for v in vios])
        draft = _agent.run({**state, "_slide": planned, "_tighten": hint})
    return _draft_to_content(planned, draft)


def node(state: GraphState) -> dict:
    """LangGraph node: write every planned slide -> list[SlideContent]."""
    plan = state["plan"]
    slides = [write_one(state, p) for p in plan.slides]
    logger.info("[deck_writer] wrote %d slides", len(slides))
    return {"slides": slides, "status": "running"}