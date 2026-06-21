"""
ai/rendering/slot_map.py
========================
The layout library. Every editable slot on every slide of the ICICI Prudential
AMC template, with real capacities extracted from the file itself.

Two consumers:
  * the OUTLINE PLANNER (ai/agents/manager.py) selects from `selectable` layouts,
    matching a slide's kind (data vs narrative) to the topic.
  * the FIT VALIDATOR (ai/rendering/fit_validator.py) reads slot capacities to
    enforce that generated content fits without overflow.

Slide roles:
  * FIXED       — slides 1 (title), 2 (agenda), 16 (thank-you): used once, in place.
  * SELECTABLE  — content slides the planner may pick freely.
  * INSTRUCTIONAL — slides 14, 15 (colour guide / RGB spec): excluded from output.

`font_pt` values are nominal (the visible sizes from the template) and feed the
char-budget estimate; they are not re-read per run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    TITLE = "title"
    AGENDA = "agenda"
    THANKYOU = "thankyou"
    NARRATIVE = "narrative"
    DATA = "data"
    INSTRUCTIONAL = "instructional"


@dataclass(frozen=True)
class TextSlot:
    role: str            # title | subtitle | heading | body | description | date | closing | footer
    name: str            # placeholder name — the renderer's lookup key
    max_lines: int       # structural paragraph capacity in the template
    width_in: float | None
    font_pt: int         # nominal visible size
    clear: bool = False  # footers carry template boilerplate → blank them
    fit_box: bool = False  # resize the shape width to width_in at render (keeps text out of a neighbour)
    render_font_pt: int | None = None  # force a smaller run font so max_lines fit a short box


@dataclass(frozen=True)
class TableSlot:
    rows: int
    cols: int
    header_rows: int = 1


@dataclass(frozen=True)
class SmartArtSlot:
    data: str            # diagrams/<data>.xml
    drawing: str         # diagrams/<drawing>.xml  (the render cache — must also be edited)
    labels: int          # number of node labels to supply, in order


@dataclass(frozen=True)
class ImageSlot:
    media: str           # ppt/media/<file> to overwrite (chart fallback PNG)
    w: int = 1280        # original media pixel size (render charts/images to this aspect)
    h: int = 720
    kind: str = "chart"  # swappable: real chart (data topic) or illustration (narrative fallback)


@dataclass(frozen=True)
class Layout:
    slide: int
    layout_id: str
    kind: Kind
    selectable: bool
    text: list[TextSlot] = field(default_factory=list)
    table: TableSlot | None = None
    smartart: SmartArtSlot | None = None
    image: ImageSlot | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
SLOT_MAP: dict[int, Layout] = {
    1: Layout(1, "title", Kind.TITLE, selectable=False, text=[
        TextSlot("title",    "Text Placeholder 1", 1, 6.30, 48),
        TextSlot("subtitle", "Text Placeholder 2", 2, 5.71, 24),
        TextSlot("date",     "Text Placeholder 3", 1, 4.49, 20),
    ], notes="Cover. Orange swoosh + logo are template — never touched."),

    2: Layout(2, "agenda", Kind.AGENDA, selectable=False, text=[
        TextSlot("heading", "Text Placeholder 2", 2, 12.78, 32),
        TextSlot("body",    "Text Placeholder 3", 5, 6.36, 24),
    ], notes="image5 is the decorative swoosh — NOT swappable."),

    3: Layout(3, "content_bullets", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",    "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("subtitle", "Text Placeholder 4", 2, 12.78, 24, render_font_pt=18),
        TextSlot("body",     "Text Placeholder 5", 6, 12.78, 24),
        TextSlot("footer",   "Footer Placeholder 2", 3, 7.67, 16, clear=True),
    ], notes="Body paragraph 2 carries the template's bold-emphasis style."),

    4: Layout(4, "content_chart", Kind.DATA, selectable=True, text=[
        TextSlot("title",    "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("subtitle", "Text Placeholder 7", 1, 5.44, 24),
        TextSlot("block_a",  "Text Placeholder 3", 1, 6.25, 20),
        TextSlot("block_b",  "Text Placeholder 4", 2, 6.24, 20),
        TextSlot("body",     "Text Placeholder 5", 6, 5.35, 24, fit_box=True),
        TextSlot("footer",   "Footer Placeholder 5", 2, None, 16, clear=True),
    ], image=ImageSlot("image6.png", w=1090, h=568, kind="chart"),
       notes="Pie-chart fallback (OLE). Data topic -> real chart PNG; narrative -> illustration."),

    5: Layout(5, "table_2col", Kind.DATA, selectable=True, text=[
        TextSlot("title", "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("body",  "Text Placeholder 6", 5, 5.86, 24),
        TextSlot("footer","Footer Placeholder 4", 1, 10.42, 16, clear=True),
    ], table=TableSlot(7, 3)),

    6: Layout(6, "table_3col", Kind.DATA, selectable=True, text=[
        TextSlot("title",    "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("subtitle", "Text Placeholder 3", 1, 12.66, 24),
        TextSlot("footer",   "Footer Placeholder 4", 2, None, 16, clear=True),
    ], table=TableSlot(9, 4),
       notes="Bold rows (header + any emphasis row) need a wider char budget — see fit_validator."),

    7: Layout(7, "table_5col", Kind.DATA, selectable=True, text=[
        TextSlot("title",  "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("footer", "Footer Placeholder 4", 2, None, 16, clear=True),
    ], table=TableSlot(7, 6),
       notes="Widest table — keep cell text terse; 6 columns wrap easily."),

    8: Layout(8, "content_barchart", Kind.DATA, selectable=True, text=[
        TextSlot("title",    "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("subtitle", "Text Placeholder 2", 2, 5.11, 24, render_font_pt=18),
        TextSlot("footer",   "Footer Placeholder 4", 1, None, 16, clear=True),
    ], image=ImageSlot("image7.png", w=1967, h=755, kind="chart"),
       notes="Bar-chart fallback (OLE)."),

    9: Layout(9, "smartart_hierarchy", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",       "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("description", "Text Placeholder 3", 5, 5.33, 24),
        TextSlot("footer",      "Footer Placeholder 3", 3, None, 16, clear=True),
    ], smartart=SmartArtSlot("data1", "drawing1", 6),
       notes="Hierarchy: 1 root -> 2 children -> grandchildren."),

    10: Layout(10, "smartart_process", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",       "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("description", "Text Placeholder 3", 4, 5.92, 24),
        TextSlot("footer",      "Footer Placeholder 3", 3, None, 16, clear=True),
    ], smartart=SmartArtSlot("data2", "drawing2", 6),
       notes="Process / flow."),

    11: Layout(11, "smartart_cards", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",  "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("footer", "Footer Placeholder 3", 2, None, 16, clear=True),
    ], smartart=SmartArtSlot("data3", "drawing3", 8),
       notes="2x4 coloured card grid — 8 short labels."),

    12: Layout(12, "smartart_chevron", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",  "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("footer", "Footer Placeholder 3", 1, None, 16, clear=True),
    ], smartart=SmartArtSlot("data4", "drawing4", 15),
       notes="Chevron sequence — 15 nodes (≈5 steps x header+sublines). Keep each terse."),

    13: Layout(13, "smartart_hexagon", Kind.NARRATIVE, selectable=True, text=[
        TextSlot("title",       "Text Placeholder 1", 1, 12.78, 32),
        TextSlot("description", "Text Placeholder 3", 3, 5.92, 24),
        TextSlot("footer",      "Footer Placeholder 3", 3, None, 16, clear=True),
    ], smartart=SmartArtSlot("data5", "drawing5", 6),
       notes="Honeycomb / interlocking concepts."),

    14: Layout(14, "guide_colours", Kind.INSTRUCTIONAL, selectable=False,
               notes="Brand colour usage guide — excluded from generated output."),

    15: Layout(15, "guide_rgb", Kind.INSTRUCTIONAL, selectable=False,
               notes="RGB spec swatches — excluded from generated output."),

    16: Layout(16, "thankyou", Kind.THANKYOU, selectable=False, text=[
        TextSlot("closing", "Text Placeholder 1", 4, 6.30, 48),
    ], notes="Closing. Orange swoosh + logo are template."),
}


# ---------------------------------------------------------------------------
# Helpers for the planner & fit validator
# ---------------------------------------------------------------------------
def content_layouts(kind: Kind | None = None) -> list[Layout]:
    """Selectable layouts the planner may choose, optionally filtered by kind."""
    out = [l for l in SLOT_MAP.values() if l.selectable]
    if kind is not None:
        out = [l for l in out if l.kind == kind]
    return out


def by_id(layout_id: str) -> Layout:
    for l in SLOT_MAP.values():
        if l.layout_id == layout_id:
            return l
    raise KeyError(layout_id)


def char_budget(slot: TextSlot, bold: bool = False) -> int:
    """Approx max characters per line for a text slot.

    Heuristic: glyphs/inch ~= 144 / font_pt for a proportional font; bold glyphs
    are ~10% wider, so the budget shrinks. width_in=None (anchored boxes) returns
    a generous default — those slots wrap freely.
    """
    if slot.width_in is None:
        return 60
    budget = slot.width_in * 144 / slot.font_pt
    if bold:
        budget *= 0.9
    return int(budget)


if __name__ == "__main__":
    print("Selectable DATA layouts:    ",
          [l.layout_id for l in content_layouts(Kind.DATA)])
    print("Selectable NARRATIVE layouts:",
          [l.layout_id for l in content_layouts(Kind.NARRATIVE)])
    print("Excluded (instructional):   ",
          [l.layout_id for l in SLOT_MAP.values() if l.kind == Kind.INSTRUCTIONAL])
    print("\nExample char budgets:")
    s3 = by_id("content_bullets")
    for ts in s3.text:
        print(f"  {s3.layout_id}/{ts.role:11s} max_lines={ts.max_lines} "
              f"char_budget={char_budget(ts)}")


# ---------------------------------------------------------------------------
# Planner catalog: a compact, LLM-readable summary of selectable layouts.
# Injected into the manager's prompt so it can only plan with REAL layouts.
# ---------------------------------------------------------------------------
def catalog_for_planner() -> str:
    """One line per selectable layout: id, kind, and what it holds."""
    lines = []
    for lay in SLOT_MAP.values():
        if not lay.selectable:
            continue
        parts = []
        for ts in lay.text:
            if ts.role == "footer":
                continue
            parts.append(f"{ts.role}(<={ts.max_lines} line{'s' if ts.max_lines > 1 else ''})")
        if lay.table:
            parts.append(f"table({lay.table.rows}x{lay.table.cols})")
        if lay.smartart:
            parts.append(f"smartart({lay.smartart.labels} labels)")
        if lay.image:
            parts.append("image(swappable)")
        lines.append(f"- {lay.layout_id} [{lay.kind.value}]: {', '.join(parts)}")
    return "\n".join(lines)


if __name__ == "__main__" and False:
    pass


def writer_brief(layout) -> str:
    """Per-layout instructions for the content writer: which slots to fill + limits."""
    lines = [f"Layout '{layout.layout_id}' [{layout.kind.value}]. Produce content for these slots:"]
    for ts in layout.text:
        if ts.role == "footer":
            continue
        lines.append(f"- {ts.role}: up to {ts.max_lines} line(s), each <= ~{char_budget(ts)} characters")
    if layout.table:
        lines.append(f"- table_rows: {layout.table.cols} columns (row 1 = header). "
                     f"Use {min(layout.table.rows, 6)}-{layout.table.rows} rows. EACH CELL MUST BE "
                     f"EXTREMELY TERSE: a number or 1-3 words (<=15 chars). NEVER write phrases, "
                     f"sentences, or parentheticals in a cell; use abbreviations (e.g. 'PSBs', "
                     f"'~59%', '>51%'). Every row must have exactly {layout.table.cols} cells.")
    if layout.smartart:
        lines.append(f"- smartart: exactly {layout.smartart.labels} short node labels "
                     f"(1-3 words each), in logical order.")
    if layout.image:
        lines.append("- NOTE: this layout has a visual region; do NOT write image content, "
                     "only the text slots above.")
    return "\n".join(lines)