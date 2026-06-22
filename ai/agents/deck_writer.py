"""
ai/agents/deck_writer.py -- (3) per-slot content reasoner (Gemini 2.5 Pro)

Per-slide: turns one PlannedSlide into a SlideContent that fits the layout's
capacities and flows straight into the renderer. The node loops the approved
plan, fit-validates each slide, and does ONE tightening retry on overflow.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ai.agents.base import BaseAgent
from ai.agents_prompts.deck_writer import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import SlideDraft, SlideContent, SlotContent, PlannedSlide
from ai.graph.state import GraphState
from ai.rendering.slot_map import by_id, writer_brief
from ai.rendering import fit_validator as fv
from ai.config_env import settings
from ai.src.logger import get_logger, bind_slide

logger = get_logger(__name__)


class DeckWriter(BaseAgent[SlideDraft]):
    task = "deck_writer"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = SlideDraft
    temperature = 0.0

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
        ev = state.get("_evidence")
        if ev:
            msg += ("\n\nGROUNDING EVIDENCE (base all figures on this; do NOT invent "
                    "numbers beyond it. If a needed figure is absent here, state it "
                    "qualitatively rather than inventing a precise value):\n" + ev)
        if state.get("_tighten"):
            msg += f"\n\nIMPORTANT: {state['_tighten']}"
        return msg


_agent = DeckWriter()


def _draft_to_content(planned: PlannedSlide, draft: SlideDraft) -> SlideContent:
    text = {s.role: SlotContent(lines=list(s.lines)) for s in draft.slots}
    table = [list(r.cells) for r in draft.table_rows] if draft.table_rows else None
    return SlideContent(slide=planned.slide, layout_id=planned.layout_id,
                        text=text, table=table, smartart=draft.smartart)


def _validate(draft: SlideDraft, layout, tol: float = 0.0) -> list:
    vios = []
    for s in draft.slots:
        ts = fv.slot_by_role(layout, s.role)
        if ts is None:
            vios.append(fv.Violation(s.role, "unknown_slot", f"role '{s.role}' not in layout"))
            continue
        vios += fv.check_text(s.role, ts, s.lines, tol=tol)
    if layout.table and draft.table_rows:
        vios += fv.check_table([list(r.cells) for r in draft.table_rows], layout)
    if layout.smartart and draft.smartart is not None:
        vios += fv.check_smartart(draft.smartart, layout)
    return vios


def _combine_evidence(curated: str, web: str) -> str:
    """User files are authoritative ground truth; web is supplementary. Labels make
    the hierarchy explicit to both the writer and the judge (user_file > web)."""
    parts = []
    if curated:
        parts.append("USER-PROVIDED SOURCE MATERIAL (authoritative ground truth -- prefer "
                     "this; if it conflicts with web data, this wins):\n" + curated)
    if web:
        parts.append("WEB EVIDENCE (supplementary; use where the user material is silent):\n" + web)
    return "\n\n".join(parts)


def write_one(state: GraphState, planned: PlannedSlide,
              evidence_sink: dict | None = None) -> SlideContent:
    layout = by_id(planned.layout_id)

    # Ground truth from user files (curated, whole-deck). Web search ONLY when
    # necessary -- i.e. no user-file evidence is available for grounding.
    curated = state.get("curated_evidence") or ""
    web_evidence, sources = "", []
    if planned.kind == "data" and not curated:
        from ai.agents.web_search import gather
        web_evidence, sources = gather(state["query"], planned.title)

    # The writer sees both (user_file preferred); the judge gets curated from its
    # own state channel, so the sink carries ONLY the web part to avoid duplication.
    if evidence_sink is not None and web_evidence:
        evidence_sink[planned.slide] = web_evidence
    evidence = _combine_evidence(curated, web_evidence)

    ctx = {**state, "_slide": planned, "_evidence": evidence}
    grounding = "user-files" if curated else ("web" if web_evidence else "narrative/none")
    logger.info("[deck_writer] slide %s (%s): writing -- grounding=%s",
                planned.slide, planned.layout_id, grounding)
    draft = _agent.run(ctx)
    # Retry only on SIGNIFICANT overflow (>15% over a line budget) or structural
    # issues (too many lines / bad grid / wrong label count). Minor 1-3 char
    # overshoots are absorbed by shrink-to-fit, so they don't justify a re-gen.
    vios = _validate(draft, layout, tol=0.15)
    if vios:
        hint = ("Some content did not fit. Fix these and keep everything within limits: "
                + "; ".join(v.detail for v in vios[:4]))
        logger.warning("[deck_writer] slide %s (%s) fit issues, one retry: %s",
                       planned.slide, planned.layout_id, [v.kind for v in vios])
        draft = _agent.run({**ctx, "_tighten": hint})

    content = _draft_to_content(planned, draft)
    if sources and content.text:
        # attach provenance to the slide's first content slot
        next(iter(content.text.values())).sources = sources
    return content


def node(state: GraphState) -> dict:
    """LangGraph node: write every planned slide -> list[SlideContent].

    Slides are independent, so they're written concurrently in a bounded thread pool
    (settings.max_workers). Each task tags its logs with its slide id and writes its
    web-evidence into a LOCAL dict; the node merges them afterward, so no shared
    mutable state races across workers."""
    plan = state["plan"]
    n = len(plan.slides)
    workers = max(1, min(settings.max_workers, n))
    logger.info("[deck_writer] writing %d slides (concurrency=%d)...", n, workers)

    def _one(p: PlannedSlide):
        local: dict[int, str] = {}
        with bind_slide(p.slide):
            sc = write_one(state, p, local)
        return sc, local

    if workers == 1 or n == 1:
        results = [_one(p) for p in plan.slides]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_one, plan.slides))   # ex.map preserves plan order

    slides = [sc for sc, _ in results]
    evidence_by_slide: dict[int, str] = {}
    for _, local in results:
        evidence_by_slide.update(local)
    logger.info("[deck_writer] wrote %d slides (concurrency=%d)", len(slides), workers)
    return {"slides": slides, "evidence_by_slide": evidence_by_slide, "status": "running"}