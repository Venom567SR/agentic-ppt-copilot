"""
ai/rendering/fit_validator.py
=============================
Deterministic fit enforcement. No LLM. Given a slide's content and its Layout
from slot_map, report every capacity violation so the agent layer can regenerate
just the offending slot (or, in the deterministic test driver, truncate-and-warn).

Checks:
  * text slot: line count <= max_lines; each line <= char_budget
  * table:     rows/cols within grid; header + emphasis rows use a wider budget
  * smartart:  label count matches the diagram's node count exactly
"""
from __future__ import annotations

from dataclasses import dataclass

from ai.rendering.slot_map import Layout, TextSlot, char_budget  # repo: ai.rendering.slot_map


@dataclass
class Violation:
    slot: str        # e.g. "body", "table[5][1]", "smartart"
    kind: str        # "too_many_lines" | "line_too_long" | "grid_overflow" | "label_count"
    detail: str


# --- text -------------------------------------------------------------------
def check_text(role: str, slot: TextSlot, lines: list[str],
               bold: bool = False) -> list[Violation]:
    out: list[Violation] = []
    if len(lines) > slot.max_lines:
        out.append(Violation(role, "too_many_lines",
                             f"{len(lines)} lines > capacity {slot.max_lines}"))
    budget = char_budget(slot, bold=bold)
    for i, ln in enumerate(lines):
        if len(ln) > budget:
            out.append(Violation(f"{role}[{i}]", "line_too_long",
                                 f"{len(ln)} chars > budget {budget}: {ln[:40]!r}…"))
    return out


# --- table ------------------------------------------------------------------
# A cell's char budget ~ column width. We approximate column width from the
# slide width (12.78in usable) split across columns, minus padding.
def _cell_budget(cols: int, font_pt: int = 20, bold: bool = False) -> int:
    usable_in = 12.0 / cols
    budget = usable_in * 144 / font_pt
    if bold:
        budget *= 0.9
    return int(budget)


def check_table(rows: list[list[str]], layout: Layout) -> list[Violation]:
    out: list[Violation] = []
    t = layout.table
    if t is None:
        return [Violation("table", "grid_overflow", "layout has no table")]
    if len(rows) > t.rows:
        out.append(Violation("table", "grid_overflow",
                             f"{len(rows)} rows > {t.rows}"))
    for r, row in enumerate(rows):
        if len(row) > t.cols:
            out.append(Violation(f"table[{r}]", "grid_overflow",
                                 f"{len(row)} cols > {t.cols}"))
        # header rows render bold (wider glyphs) -> tighter budget
        bold = r < t.header_rows
        budget = _cell_budget(t.cols, bold=bold)
        for c, cell in enumerate(row):
            if len(str(cell)) > budget:
                out.append(Violation(f"table[{r}][{c}]", "line_too_long",
                                     f"{len(str(cell))} chars > {budget}: {str(cell)[:24]!r}…"))
    return out


# --- smartart ---------------------------------------------------------------
def check_smartart(labels: list[str], layout: Layout) -> list[Violation]:
    sa = layout.smartart
    if sa is None:
        return [Violation("smartart", "label_count", "layout has no smartart")]
    if len(labels) != sa.labels:
        return [Violation("smartart", "label_count",
                          f"{len(labels)} labels != required {sa.labels}")]
    return []


def slot_by_role(layout: Layout, role: str) -> TextSlot | None:
    for ts in layout.text:
        if ts.role == role:
            return ts
    return None