# """
# ai/agents/ppt_generator.py -- (4) renderer driver. NOT a BaseAgent (no LLM).

# Consumes the finalized SlideContent objects and calls ai/rendering/ to write
# them into the per-run unpacked template, then repacks. Pure orchestration of
# deterministic steps.
# """
# # from ai.rendering import template_renderer, slot_map, pptx_io, workspace


# def render_deck(state) -> str:
#     """Apply approved content to the template; return path to the packed .pptx."""
#     raise NotImplementedError  # TODO

"""
ai/agents/ppt_generator.py  (driver — NOT a BaseAgent; deterministic, no LLM)
=============================================================================
Consumes a finalized deck spec and produces a branded .pptx by:
  1. make_run_dir -> isolated per-run unpacked template
  2. for each planned slide: fit-validate -> apply via template_renderer
  3. drop/reorder slides to exactly the planned subset (sldIdLst)
  4. pack -> deck.pptx

Spec format (one entry per output slide, in order):
  {"slide": int, "layout_id": str,
   "text": {role: [lines]}, "table": [[...]], "smartart": [labels], "image": path}
"""
from __future__ import annotations

import re
from pathlib import Path
from lxml import etree

from ai.rendering import template_renderer as tr
from ai.rendering import fit_validator as fv
from ai.rendering.slot_map import SLOT_MAP, by_id
from ai.rendering.pptx_io import pack
from ai.rendering.workspace import make_run_dir

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# --- apply content to one slide --------------------------------------------
def apply_slide(unpacked: Path, slide_no: int, layout, content: dict,
                warnings: list[str]) -> None:
    sl = unpacked / "ppt" / "slides" / f"slide{slide_no}.xml"
    tree = tr.load_xml(sl)
    root = tree.getroot()

    # text slots (by role -> placeholder name)
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
        elif ts.clear:  # footer boilerplate -> blank
            sp = tr.shape_by_name(root, ts.name)
            if sp is not None:
                tr.set_shape_lines(sp, [""])

    # table
    if "table" in content:
        for v in fv.check_table(content["table"], layout):
            warnings.append(f"slide{slide_no}/{v.slot}: {v.detail}")
        tr.set_table(root, content["table"])

    tr.save_xml(tree, sl)

    # smartart (separate data + drawing files)
    if "smartart" in content and layout.smartart:
        for v in fv.check_smartart(content["smartart"], layout):
            warnings.append(f"slide{slide_no}/smartart: {v.detail}")
        dg = unpacked / "ppt" / "diagrams"
        dt = tr.load_xml(dg / f"{layout.smartart.data}.xml")
        dr = tr.load_xml(dg / f"{layout.smartart.drawing}.xml")
        tr.set_smartart_full(dt.getroot(), dr.getroot(), content["smartart"])
        tr.save_xml(dt, dg / f"{layout.smartart.data}.xml")
        tr.save_xml(dr, dg / f"{layout.smartart.drawing}.xml")

    # image swap (chart fallback / illustration)
    if "image" in content and layout.image:
        tr.swap_image(unpacked / "ppt" / "media" / layout.image.media,
                      Path(content["image"]))


# --- keep/reorder slides via sldIdLst --------------------------------------
def select_slides(unpacked: Path, ordered_slides: list[int]) -> None:
    rels = (unpacked / "ppt" / "_rels" / "presentation.xml.rels").read_text()
    slide_to_rid = {int(re.search(r"slide(\d+)\.xml", t).group(1)): rid
                    for rid, t in re.findall(r'Id="([^"]+)"[^>]*Target="(slides/slide\d+\.xml)"', rels)}

    pres = unpacked / "ppt" / "presentation.xml"
    tree = tr.load_xml(pres)
    root = tree.getroot()
    lst = root.find(f"{{{NS_P}}}sldIdLst")
    rid_to_sldid = {sld.get(f"{{{NS_R}}}id"): sld for sld in lst}

    for sld in list(lst):
        lst.remove(sld)
    for n in ordered_slides:
        rid = slide_to_rid[n]
        lst.append(rid_to_sldid[rid])
    tr.save_xml(tree, pres)


# --- top-level driver -------------------------------------------------------
def render_deck(spec: list[dict], thread_id: str, template_path: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    rp = make_run_dir(thread_id, template_path)
    order = [e["slide"] for e in spec]
    for e in spec:
        apply_slide(rp.unpacked, e["slide"], by_id(e["layout_id"]), e, warnings)
    select_slides(rp.unpacked, order)
    pack(rp.unpacked, rp.deck)
    return str(rp.deck), warnings