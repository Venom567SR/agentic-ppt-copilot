"""
ai/utils/provenance.py
======================
Turns a finished run's state into a structured PROVENANCE record: for each slide,
which claims it makes, what they are grounded in, and whether they were verified,
softened, or unsupported.

Pure logic over state (no LLM, no rendering) -> fully testable. NOT written into the
.pptx (the deck stays clean); saved as runs/<thread_id>/provenance.json and returned
in the API response so a frontend can render a "claim -> source -> status" table
beneath the deck preview.

Citations (honest scope):
- Web-grounded claims carry the SLIDE'S source set -- the {title, url} pairs gathered
  for that slide (already attached to SlideContent.sources by the writer). This is
  slide-level attribution (Perplexity-ish, clickable), NOT a verified per-claim URL
  mapping; pinning each claim to one URL would need the judge to emit a locator.
- User-file claims cite the uploaded file(s) at file level.
- Only DATA slides are claim-verified by the judge. Narrative slides carry no
  per-claim check and are reported as "conceptual -- not source-verified".

`source` is ALWAYS a list of {title, url} objects so the frontend renders a uniform
cell (clickable chip when url is non-empty).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

from ai.rendering.slot_map import describe_layout

GROUNDED = "grounded"        # judge verified the claim against a source
SOFTENED = "softened"        # flagged unsupported, then rewritten qualitatively by repair
UNSUPPORTED = "unsupported"  # flagged and NOT repaired (rare)

_NONE_SOURCE = [{"title": "not found in sources -- stated qualitatively", "url": ""}]
_FILE_SOURCE = [{"title": "Uploaded files", "url": ""}]


@dataclass
class ClaimProvenance:
    claim: str
    status: str                  # grounded | softened | unsupported
    authority: str               # user_file | web | none
    source: list[dict]           # [{title, url}] -- url empty for file/none


@dataclass
class SlideProvenance:
    position: int                # 1-based deck order
    slide: int                   # physical template slide number
    title: str
    layout: str                  # human-readable layout label
    kind: str                    # data | narrative
    verified: bool               # was this slide claim-checked by the judge?
    note: str = ""               # set for non-verified (narrative) slides
    claims: list[ClaimProvenance] = field(default_factory=list)


@dataclass
class RunProvenance:
    deck_title: str
    sources: list[dict]          # union of all {title, url} cited across the deck
    slides: list[SlideProvenance]

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def n_grounded(self) -> int:
        return sum(1 for s in self.slides for c in s.claims if c.status == GROUNDED)

    @property
    def n_softened(self) -> int:
        return sum(1 for s in self.slides for c in s.claims if c.status == SOFTENED)


def _basename(p: str) -> str:
    return os.path.basename(p.replace("\\", "/"))


def _file_sources(user_files: list[str]) -> list[dict]:
    return [{"title": f, "url": ""} for f in user_files] or [{"title": "uploaded files", "url": ""}]


def _web_sources_for(slide_sources) -> list[dict]:
    """Deduped {title, url} chips from a slide's attached web Sources."""
    seen, out = set(), []
    for s in slide_sources:
        if getattr(s, "authority", None) != "web":
            continue
        url = getattr(s, "url", "")
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": getattr(s, "title", "") or url, "url": url})
    return out or [{"title": "web search", "url": ""}]


def _softened_slides(fallbacks) -> set[int]:
    out: set[int] = set()
    for fb in fallbacks or []:
        m = re.search(r"slide\s+(\d+)", getattr(fb, "reason", "") or "")
        if m:
            out.add(int(m.group(1)))
    return out


def build_provenance(state) -> RunProvenance:
    """Build the provenance record from final run state (after render)."""
    plan = state.get("plan")
    guardrail = state.get("guardrail") or {}
    user_files = [_basename(p) for p in (state.get("user_files") or [])]
    softened = _softened_slides(state.get("fallbacks"))

    # physical slide -> its attached web sources (writer put these on SlideContent)
    web_by_slide: dict[int, list] = {}
    for sc in (state.get("slides") or []):
        try:
            web_by_slide[sc.slide] = [s for s in sc.all_sources()
                                      if getattr(s, "authority", None) == "web"]
        except Exception:
            pass

    file_sources = _file_sources(user_files)        # real filenames (for the deck-level panel)

    def _cite(authority: str, slide_no: int) -> list[dict]:
        # We know a claim is file-grounded, but the judge does not emit WHICH file,
        # so we cite "Uploaded files" honestly rather than implying all files support it.
        # The actual filenames are listed once in the deck-level `sources` panel.
        if authority == "user_file":
            return list(_FILE_SOURCE)
        if authority == "web":
            return _web_sources_for(web_by_slide.get(slide_no, []))
        return _NONE_SOURCE

    slides: list[SlideProvenance] = []
    if plan is not None:
        for i, ps in enumerate(plan.slides, 1):
            gr = guardrail.get(ps.slide)
            layout = describe_layout(ps.layout_id)
            if gr is None:
                slides.append(SlideProvenance(
                    position=i, slide=ps.slide, title=ps.title, layout=layout,
                    kind=ps.kind, verified=False,
                    note="Conceptual framing -- not source-verified"))
                continue
            claims = []
            for c in gr.checks:
                if c.supported:
                    status = GROUNDED
                elif ps.slide in softened:
                    status = SOFTENED
                else:
                    status = UNSUPPORTED
                claims.append(ClaimProvenance(
                    claim=c.claim, status=status, authority=c.authority,
                    source=_cite(c.authority, ps.slide)))
            slides.append(SlideProvenance(
                position=i, slide=ps.slide, title=ps.title, layout=layout,
                kind=ps.kind, verified=True, claims=claims))

    # Deck-level source list: the real uploaded filenames (shown once) + every web URL.
    # Skips the per-claim "Uploaded files"/"none" placeholders so the panel stays meaningful.
    seen, union = set(), []

    def _add(src: dict):
        key = (src["title"], src["url"])
        if key not in seen:
            seen.add(key)
            union.append(src)

    if any(c.authority == "user_file" for s in slides for c in s.claims):
        for src in file_sources:
            _add(src)
    for s in slides:
        for c in s.claims:
            for src in c.source:
                if src["url"]:                       # web chips (url-bearing) only
                    _add(src)

    return RunProvenance(
        deck_title=getattr(plan, "deck_title", "") if plan else "",
        sources=union,
        slides=slides,
    )


def save(rp: RunProvenance, thread_id: str, runs_dir: str | Path = "runs") -> str:
    path = Path(runs_dir) / str(thread_id) / "provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _fmt_sources(srcs: list[dict], max_n: int = 3) -> str:
    chips = [(s["url"] or s["title"]) for s in srcs[:max_n]]
    extra = f" (+{len(srcs) - max_n} more)" if len(srcs) > max_n else ""
    return ", ".join(chips) + extra


def print_table(rp: RunProvenance, max_claim: int = 60) -> None:
    print("\n===== PROVENANCE (claim -> source) =====")
    for s in rp.slides:
        head = f"  {s.position}. {s.title}  [{s.layout}]"
        if not s.verified:
            print(f"{head}\n       {s.note}")
            continue
        print(head)
        for c in s.claims:
            claim = (c.claim[:max_claim] + "…") if len(c.claim) > max_claim else c.claim
            print(f"       [{c.status:11s}] {claim}")
            print(f"                    source: {_fmt_sources(c.source)}")
    print(f"\n  {rp.n_grounded} claim(s) grounded · {rp.n_softened} softened · "
          f"{len(rp.sources)} distinct source(s)")