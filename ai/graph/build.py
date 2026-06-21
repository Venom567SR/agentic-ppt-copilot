"""
ai/graph/build.py -- the one runnable LangGraph (structured backbone + supervisor)

Wires every agent/node into a single graph:

    START
      -> intent                         (1) intent guard
      -> [route_after_intent]
            block   -> END
            ingest  -> ingest -> scope  (build corpus map; supervisor scope check)
            clarify -> clarify
      ingest/scope -> clarify
      -> clarify                        (1) clarifier        ── HITL GATE 1 ──
      -> manager                        (2) planner          ── HITL GATE 2 ──
      -> [route_after_plan]
            curate  -> curate -> write  (curate user-file evidence vs the agenda)
            write   -> write
      -> write                          (3) deck_writer (grounded)
      -> images                         (3) image_generator (charts/illustrations)
      -> judge                          (4) grounding guardrail
      -> [route_after_judge]
            repair  -> repair -> render (soften unsupported claims, one shot)
            render  -> render
      -> render                         (5) ppt_generator -> branded .pptx
      -> END

HITL: compiled with interrupt_after=["clarify", "manager"] + a checkpointer, so
the graph pauses at the two gates. The caller injects the user's reply with
update_state(...) and resumes with invoke(None, config). Routing decisions are
the supervisor's (rules + one LLM judgment); this module only assembles.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from ai.graph.state import GraphState
from ai.agents import (
    intent_detector, research_agent, manager, deck_writer, image_generator,
    judge, context_retriever, ppt_generator, supervisor,
)
from ai.schemas import FallbackDecision
from ai.src.logger import get_logger

logger = get_logger(__name__)


# ── repair node (one-shot degradation: soften unsupported claims) ────────────────
def repair_node(state: GraphState) -> dict:
    """Re-write only the data slides whose grounding failed, instructing the writer
    to drop/qualify the unsupported claims. One shot (no re-judge loop), so the
    run stays bounded. The fuller degradation ladder layers on here later."""
    guardrail = state.get("guardrail") or {}
    plan = state["plan"]
    planned_by = {p.slide: p for p in plan.slides}
    by_slide = {sc.slide: sc for sc in state["slides"]}
    fallbacks: list[FallbackDecision] = []

    for slide_no, result in guardrail.items():
        if result.passed:
            continue
        bad = [c.claim for c in result.checks if not c.supported]
        planned = planned_by.get(slide_no)
        if not planned or not bad:
            continue
        hint = ("Remove or make qualitative these unsupported claims -- do NOT state "
                "them as precise facts: " + "; ".join(bad[:5]))
        try:
            old_sc = by_slide[slide_no]
            new_sc = deck_writer.write_one({**state, "_tighten": hint}, planned)
            # Repair only softens TEXT. Carry over the chart/image (and smartart) that
            # image_generator already produced for this slide, or it renders with the
            # template's default placeholder chart.
            new_sc.image = old_sc.image
            if new_sc.smartart is None:
                new_sc.smartart = old_sc.smartart
            by_slide[slide_no] = new_sc
            fallbacks.append(FallbackDecision(rung="qualitative",
                             reason=f"slide {slide_no}: unsupported claims softened"))
            logger.info("[repair] slide %s rewritten to soften %d claim(s)", slide_no, len(bad))
        except Exception as e:
            logger.warning("[repair] slide %s rewrite failed (%s); leaving as-is", slide_no, e)

    new_slides = [by_slide[sc.slide] for sc in state["slides"]]
    return {"slides": new_slides, "fallbacks": fallbacks}


def build_graph(checkpointer=None):
    """Assemble and compile the agentic graph. Pass a checkpointer (defaults to an
    in-memory one) -- required for the HITL gates to pause/resume by thread_id."""
    g = StateGraph(GraphState)

    g.add_node("intent", intent_detector.node)
    g.add_node("ingest", context_retriever.ingest_node)
    g.add_node("scope", supervisor.scope_node)
    g.add_node("clarify", research_agent.node)
    g.add_node("manager", manager.node)
    g.add_node("curate", context_retriever.curate_node)
    g.add_node("write", deck_writer.node)
    g.add_node("images", image_generator.node)
    g.add_node("judge", judge.node)
    g.add_node("repair", repair_node)
    g.add_node("render", ppt_generator.node)

    g.add_edge(START, "intent")
    g.add_conditional_edges("intent", supervisor.route_after_intent,
                            {"block": END, "ingest": "ingest", "clarify": "clarify"})
    g.add_edge("ingest", "scope")
    g.add_edge("scope", "clarify")
    g.add_edge("clarify", "manager")                       # gate 1 pauses after clarify
    g.add_conditional_edges("manager", supervisor.route_after_plan,
                            {"curate": "curate", "write": "write"})
    g.add_edge("curate", "write")
    g.add_edge("write", "images")
    g.add_edge("images", "judge")
    g.add_conditional_edges("judge", supervisor.route_after_judge,
                            {"repair": "repair", "render": "render"})
    g.add_edge("repair", "render")
    g.add_edge("render", END)

    return g.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_after=["clarify", "manager"],            # HITL gates 1 & 2
    )