"""
template_renderer.py
====================
Deterministic, in-place renderer for the ICICI Prudential AMC brand template.

Philosophy
----------
We edit the *real* PPTX XML in place. Structure, colours, fonts, swooshes and the
logo are never touched — only text content, table cells, SmartArt labels and the
chart fallback images are replaced. This is brand-safe *by construction*: there is
no regeneration step that could drift from the template.

Key subtlety handled here: PowerPoint splits a single logical line into multiple
<a:r> runs whenever formatting changes mid-line. Naive run-by-run replacement
shatters content. We therefore operate at the *paragraph* level — keep the first
run (its <a:rPr> carries font/size/colour), inject the new text into it, and drop
the remaining runs. Formatting is preserved; content is replaced.

Four capabilities:
  1. set_shape_lines  -> placeholder / text-box paragraphs   (lxml on slideN.xml)
  2. set_table        -> <a:tbl> cells                        (lxml on slideN.xml)
  3. set_smartart     -> <dgm:pt> node text                   (lxml on diagrams/dataN.xml)
  4. swap_image       -> chart fallback PNG, resized to bbox   (Pillow on media/imageN.png)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from lxml import etree
from PIL import Image

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
NS = {
    "a":   "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p":   "http://schemas.openxmlformats.org/presentationml/2006/main",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "dsp": "http://schemas.microsoft.com/office/drawing/2008/diagram",
    "r":   "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _qn(tag: str) -> str:
    """'a:t' -> '{http://...drawingml...}t'"""
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


# ---------------------------------------------------------------------------
# Paragraph-level text replacement (the core primitive)
# ---------------------------------------------------------------------------
def _set_paragraph_text(p: etree._Element, text: str) -> bool:
    """Collapse a paragraph's runs into one, preserving the first run's formatting.

    Returns False if the paragraph has no run to use as a formatting template
    (e.g. an empty paragraph carrying only <a:endParaRPr>).
    """
    runs = p.findall(_qn("a:r"))
    if not runs:
        return False

    first, *rest = runs
    t = first.find(_qn("a:t"))
    if t is None:
        t = etree.SubElement(first, _qn("a:t"))
    t.text = text

    for r in rest:
        p.remove(r)
    return True


def _txbody_paragraphs(shape: etree._Element) -> list[etree._Element]:
    """All <a:p> paragraphs inside a shape's <p:txBody>."""
    txbody = shape.find(_qn("p:txBody"))
    if txbody is None:
        return []
    return txbody.findall(_qn("a:p"))


def set_shape_lines(shape: etree._Element, lines: list[str]) -> None:
    """Map `lines` onto a shape's paragraphs.

    - paragraph i <- lines[i]
    - surplus template paragraphs (no matching line) are removed, so a 4-bullet
      template filled with 2 bullets renders 2 bullets, not 2 + 2 leftovers.
    - we never *add* paragraphs here; the fit-validator upstream guarantees
      len(lines) <= template capacity, keeping the layout brand-intact.
    """
    paras = _txbody_paragraphs(shape)
    if not paras:
        return

    txbody = shape.find(_qn("p:txBody"))
    for i, para in enumerate(paras):
        if i < len(lines):
            _set_paragraph_text(para, lines[i])
        else:
            txbody.remove(para)


# ---------------------------------------------------------------------------
# Placeholder lookup
# ---------------------------------------------------------------------------
def _placeholder_info(shape: etree._Element) -> tuple[str | None, str | None]:
    """Return (ph_type, ph_idx) for a <p:sp>, or (None, None) if not a placeholder."""
    ph = shape.find(f".//{_qn('p:ph')}")
    if ph is None:
        return (None, None)
    return (ph.get("type"), ph.get("idx"))


def shapes_by_placeholder(slide_tree: etree._Element) -> dict[tuple[str | None, str | None], etree._Element]:
    """Index every <p:sp> on a slide by its (ph_type, ph_idx) key."""
    out: dict[tuple, etree._Element] = {}
    for sp in slide_tree.iter(_qn("p:sp")):
        key = _placeholder_info(sp)
        if key != (None, None):
            out[key] = sp
    return out


def shape_by_name(slide_tree: etree._Element, name: str) -> etree._Element | None:
    """Find a <p:sp> by its authoring name (e.g. 'Text Placeholder 1')."""
    for sp in slide_tree.iter(_qn("p:sp")):
        cnvpr = sp.find(f".//{_qn('p:cNvPr')}")
        if cnvpr is not None and cnvpr.get("name") == name:
            return sp
    return None


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def set_table(slide_tree: etree._Element, rows: list[list[str]]) -> None:
    """Fill the first <a:tbl> on the slide, cell by cell, preserving cell formatting.

    `rows` is row-major. Cells beyond the template grid are ignored; template
    cells with no provided value are left as-is (caller should pad to clear them).
    """
    tbl = slide_tree.find(f".//{_qn('a:tbl')}")
    if tbl is None:
        return

    tr_list = tbl.findall(_qn("a:tr"))
    for r_idx, tr in enumerate(tr_list):
        if r_idx >= len(rows):
            break
        tc_list = tr.findall(_qn("a:tc"))
        for c_idx, tc in enumerate(tc_list):
            if c_idx >= len(rows[r_idx]):
                continue
            txbody = tc.find(_qn("a:txBody"))
            if txbody is None:
                continue
            paras = txbody.findall(_qn("a:p"))
            if paras:
                _set_paragraph_text(paras[0], str(rows[r_idx][c_idx]))
                for extra in paras[1:]:
                    txbody.remove(extra)


# ---------------------------------------------------------------------------
# SmartArt
# ---------------------------------------------------------------------------
def set_smartart(data_tree: etree._Element, labels: list[str]) -> None:
    """Replace SmartArt node text in document order.

    SmartArt text lives in diagrams/dataN.xml as <dgm:pt>/<dgm:t>/<a:p>. We target
    only real node points (those whose first paragraph has a run with text),
    skipping the structural 'doc'/transition points that carry only <a:endParaRPr>.
    """
    label_iter = iter(labels)
    for pt in data_tree.iter(_qn("dgm:pt")):
        if pt.get("type") in ("doc", "parTrans", "sibTrans"):
            continue
        t_el = pt.find(_qn("dgm:t"))
        if t_el is None:
            continue
        paras = t_el.findall(_qn("a:p"))
        if not paras or not paras[0].findall(_qn("a:r")):
            continue  # placeholder point with no text run
        try:
            new = next(label_iter)
        except StopIteration:
            break
        _set_paragraph_text(paras[0], new)
        for extra in paras[1:]:
            t_el.remove(extra)


def set_smartart_drawing(drawing_tree: etree._Element, labels: list[str]) -> None:
    """Patch the SmartArt *drawing cache* (diagrams/drawingN.xml).

    Critical: PowerPoint and LibreOffice render SmartArt from this cached drawing,
    NOT from the semantic data model. Editing only dataN.xml leaves the visible
    text stale. We collapse the first paragraph of each text-bearing <dsp:sp>,
    in document order, skipping empty shapes (connectors / structural nodes).
    Order matches the data model because the cache is generated from it.
    """
    label_iter = iter(labels)
    for sp in drawing_tree.iter(_qn("dsp:sp")):
        txbody = sp.find(_qn("dsp:txBody"))
        if txbody is None:
            continue
        paras = txbody.findall(_qn("a:p"))
        if not paras or not paras[0].findall(_qn("a:r")):
            continue  # empty shape — not a label
        try:
            new = next(label_iter)
        except StopIteration:
            break
        _set_paragraph_text(paras[0], new)
        for extra in paras[1:]:
            txbody.remove(extra)


def set_smartart_full(data_tree: etree._Element,
                      drawing_tree: etree._Element,
                      labels: list[str]) -> None:
    """Update BOTH SmartArt representations so the change is real and visible."""
    set_smartart(data_tree, labels)
    set_smartart_drawing(drawing_tree, labels)


# ---------------------------------------------------------------------------
# Image swap (chart fallback / narrative illustration)
# ---------------------------------------------------------------------------
def swap_image(media_path: Path, new_image_path: Path) -> tuple[int, int]:
    """Overwrite a media PNG with a new image resized to the ORIGINAL dimensions.

    Resizing to the original pixel box means the slide's picture geometry and the
    relationship are untouched — the new visual drops into the exact same frame.
    Returns the (w, h) it fitted to.
    """
    with Image.open(media_path) as orig:
        target_size = orig.size  # (w, h)
        target_format = orig.format or "PNG"

    with Image.open(new_image_path) as new_img:
        new_img = new_img.convert("RGB")
        fitted = new_img.resize(target_size, Image.LANCZOS)
        fitted.save(media_path, format=target_format)

    return target_size


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------
def load_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(str(path), parser)


def save_xml(tree: etree._ElementTree, path: Path) -> None:
    tree.write(str(path), xml_declaration=True, encoding="UTF-8", standalone=True)