"""
ai/agents/ppt_generator.py  (driver -- NOT a BaseAgent; deterministic, no LLM)
=============================================================================
Consumes finalized slide specs and produces a branded .pptx:
  1. make_run_dir -> isolated per-run unpacked template
  2. apply each slide (text/table/smartart/image), fit-validated
  3. footers carry the deck title (instead of blank/boilerplate)
  4. drop/reorder slides to the planned subset (sldIdLst)
  5. pack -> "<title>_<IST date>_<IST time>.pptx" (consistent, unique, findable)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.rendering import template_renderer as tr
from ai.rendering import fit_validator as fv
from ai.rendering.slot_map import by_id
from ai.rendering.pptx_io import pack
from ai.rendering.workspace import make_run_dir
from ai.src.logger import get_logger

logger = get_logger(__name__)

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_IST = timezone(timedelta(hours=5, minutes=30))


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (text or "deck").strip()).strip("_").lower()
    return (s[:max_len] or "deck")


def _ist_stamp() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d_%H%M%S")


def apply_slide(unpacked: Path, slide_no: int, layout, content: dict,
                warnings: list[str], footer_text: str | None = None) -> None:
    sl = unpacked / "ppt" / "slides" / f"slide{slide_no}.xml"
    tree = tr.load_xml(sl)
    root = tree.getroot()

    text = content.get("text", {})
    for ts in layout.text:
        if ts.role in text:
            lines = list(text[ts.role])
            vios = fv.check_text(ts.role, ts, lines)
            if any(v.kind == "too_many_lines" for v in vios):
                warnings.append(f"slide{slide_no}/{ts.role}: truncated to {ts.max_lines} lines")
                lines = lines[: ts.max_lines]
            for v in vios:
                if v.kind == "line_too_long":
                    warnings.append(f"slide{slide_no}/{v.slot}: {v.detail}")
            sp = tr.shape_by_name(root, ts.name)
            if sp is not None:
                tr.set_shape_lines(sp, lines)
                # Force a smaller font where a short box can't hold its line capacity
                # at the nominal size (subtitle-over-body overflow).
                if ts.render_font_pt:
                    tr.set_run_font(sp, ts.render_font_pt)
                # Shrink-to-fit on every text placeholder: a slight overshoot scales
                # down to fit its box instead of overflowing into neighbours.
                tr.set_autofit_shrink(sp)
                # Some template boxes are drawn wider than their column and overrun a
                # neighbour (e.g. content_chart body over the chart). Pull them in.
                if ts.fit_box and ts.width_in:
                    tr.set_shape_width(sp, ts.width_in)
        elif ts.clear:
            # Footer: carry the deck title (brand-consistent) instead of boilerplate.
            sp = tr.shape_by_name(root, ts.name)
            if sp is not None:
                tr.set_shape_lines(sp, [footer_text or ""])

    if "table" in content:
        for v in fv.check_table(content["table"], layout):
            warnings.append(f"slide{slide_no}/{v.slot}: {v.detail}")
        tr.set_table(root, content["table"])

    tr.save_xml(tree, sl)

    if "smartart" in content and layout.smartart:
        for v in fv.check_smartart(content["smartart"], layout):
            warnings.append(f"slide{slide_no}/smartart: {v.detail}")
        dg = unpacked / "ppt" / "diagrams"
        dt = tr.load_xml(dg / f"{layout.smartart.data}.xml")
        dr = tr.load_xml(dg / f"{layout.smartart.drawing}.xml")
        tr.set_smartart_full(dt.getroot(), dr.getroot(), content["smartart"])
        tr.save_xml(dt, dg / f"{layout.smartart.data}.xml")
        tr.save_xml(dr, dg / f"{layout.smartart.drawing}.xml")

    if "image" in content and layout.image:
        tr.swap_image(unpacked / "ppt" / "media" / layout.image.media,
                      Path(content["image"]))


def select_slides(unpacked: Path, ordered_slides: list[int]) -> None:
    rels = (unpacked / "ppt" / "_rels" / "presentation.xml.rels").read_text()
    slide_to_rid = {int(re.search(r"slide(\d+)\.xml", t).group(1)): rid
                    for rid, t in re.findall(r'Id="([^"]+)"[^>]*Target="(slides/slide\d+\.xml)"', rels)}
    pres = unpacked / "ppt" / "presentation.xml"
    tree = tr.load_xml(pres)
    lst = tree.getroot().find(f"{{{NS_P}}}sldIdLst")
    rid_to_sldid = {sld.get(f"{{{NS_R}}}id"): sld for sld in lst}
    for sld in list(lst):
        lst.remove(sld)
    for n in ordered_slides:
        lst.append(rid_to_sldid[slide_to_rid[n]])
    tr.save_xml(tree, pres)


def render_deck(spec: list[dict], thread_id: str, template_path: str,
                deck_title: str | None = None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    rp = make_run_dir(thread_id, template_path)
    order = [e["slide"] for e in spec]
    for e in spec:
        apply_slide(rp.unpacked, e["slide"], by_id(e["layout_id"]), e,
                    warnings, footer_text=deck_title)
    select_slides(rp.unpacked, order)

    # Consistent, unique, findable filename: <title>_<IST date>_<IST time>.pptx
    fname = f"{_slug(deck_title)}_{_ist_stamp()}.pptx" if deck_title else rp.deck.name
    out = rp.root / fname
    written = pack(rp.unpacked, out)
    return str(written), warnings


def node(state) -> dict:
    """LangGraph node: render the branded deck = cover + agenda + content + thanks."""
    from ai.config_env import settings
    plan = state["plan"]

    date_str = datetime.now(_IST).strftime("%B %d, %Y")
    cover = {"slide": 1, "layout_id": "title", "text": {
        "title": [plan.deck_title],
        "subtitle": [plan.subtitle] if getattr(plan, "subtitle", "") else [],
        "date": [date_str]}}
    agenda = {"slide": 2, "layout_id": "agenda", "text": {
        "heading": ["Agenda"],
        "body": [s.title for s in plan.slides][:5]}}
    thankyou = {"slide": 16, "layout_id": "thankyou", "text": {"closing": ["Thank you"]}}

    spec = [cover, agenda] + [sc.to_render_spec() for sc in state["slides"]] + [thankyou]
    logger.info("[render] assembling branded deck (%d content slides)...", len(state["slides"]))
    path, warnings = render_deck(spec, state["thread_id"], settings.template_path,
                                 deck_title=plan.deck_title)

    gr = state.get("guardrail") or {}
    n_claims = sum(len(r.checks) for r in gr.values())
    n_grounded = sum(1 for r in gr.values() for c in r.checks if c.supported)
    n_soft = len(state.get("fallbacks") or [])
    logger.info("[render] deck complete -> %s", path)
    logger.info("[render] grounding summary: %d/%d claims grounded across %d data slide(s), "
                "%d slide(s) softened", n_grounded, n_claims, len(gr), n_soft)

    out = {"deck_path": path, "status": "done"}
    if warnings:
        out["warnings"] = warnings
    return out