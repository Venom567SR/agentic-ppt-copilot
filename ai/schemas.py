"""
ai/schemas.py
=============
The typed contract. Every reasoning node returns one of these; the graph passes
them between nodes; the renderer consumes them. Design goals (in priority order):

  * No errors slip through  -> Pydantic v2 validation on every object.
  * No hallucinated fields   -> extra="forbid" on LLM-facing models; an invented
                                key raises ValidationError instead of being ignored.
  * Easy to trace/debug      -> small, explicit models; SlideContent serializes to
                                EXACTLY the dict the ppt_generator driver consumes,
                                so there is no translation layer to misread.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# LLM-facing models reject unknown fields; data containers stay lenient.
_STRICT = ConfigDict(extra="forbid")


# ── Provenance ──────────────────────────────────────────────────────────────
class Source(BaseModel):
    model_config = _STRICT
    url: str
    title: str
    retrieved_at: datetime
    claim_supported: str = ""
    authority: Literal["user_file", "web", "none"] = "web"  # file > web > none


# ── Guard (phase 1) ──────────────────────────────────────────────────────────
class IntentVerdict(BaseModel):
    model_config = _STRICT
    verdict: Literal["allow", "block"]
    category: Literal["ok", "hate", "violence", "illegal", "sexual", "self_harm", "other"]
    reason: str


class ClarifyingQuestions(BaseModel):
    model_config = _STRICT
    questions: list[str] = Field(min_length=1, max_length=5)


# ── Planning (phase 2) ────────────────────────────────────────────────────────
class PlannedSlide(BaseModel):
    model_config = _STRICT
    slide: int                       # template slide number to fill
    layout_id: str                   # must exist in slot_map
    title: str
    kind: Literal["data", "narrative"]


class DeckPlan(BaseModel):
    model_config = _STRICT
    deck_title: str
    slides: list[PlannedSlide] = Field(min_length=1, max_length=14)


# ── Content (phase 3) ─────────────────────────────────────────────────────────
class SlotContent(BaseModel):
    model_config = _STRICT
    lines: list[str] = Field(default_factory=list, max_length=12)  # general cap; per-slot limits in fit_validator
    sources: list[Source] = Field(default_factory=list)


class ImageSpec(BaseModel):
    model_config = _STRICT
    depict: str                      # what to draw, e.g. "Gandhi leading the Salt March, 1930"
    style_prefix: str                # brand style string, injected from config (not invented by the LLM)
    aspect_ratio: str                # nearest supported ratio to the target bbox
    safety: Literal["ok", "blocked"] = "ok"
    fallback_angle: str | None = None


class SlideContent(BaseModel):
    """Finalized content for ONE slide. Serializes to the driver's exact spec."""
    model_config = _STRICT
    slide: int
    layout_id: str
    text: dict[str, SlotContent] = Field(default_factory=dict)   # role -> content
    table: list[list[str]] | None = None
    smartart: list[str] | None = None
    image: str | None = None         # path to the fitted image, set by the image pipeline

    def to_render_spec(self) -> dict:
        """Flatten to the dict ppt_generator.render_deck() consumes. Zero glue."""
        spec: dict = {
            "slide": self.slide,
            "layout_id": self.layout_id,
            "text": {role: sc.lines for role, sc in self.text.items()},
        }
        if self.table is not None:
            spec["table"] = self.table
        if self.smartart is not None:
            spec["smartart"] = self.smartart
        if self.image is not None:
            spec["image"] = self.image
        return spec

    def all_sources(self) -> list[Source]:
        """Every source backing this slide — for the provenance assembler."""
        out: list[Source] = []
        for sc in self.text.values():
            out.extend(sc.sources)
        return out


# ── Degradation ladder ────────────────────────────────────────────────────────
class FallbackDecision(BaseModel):
    model_config = _STRICT
    rung: Literal["image", "qualitative", "rewrite", "drop"]
    reason: str


# ── Output guardrail (phase 5) ─────────────────────────────────────────────────
class ClaimCheck(BaseModel):
    model_config = _STRICT
    claim: str
    supported: bool
    authority: Literal["user_file", "web", "none"]
    note: str = ""


class GuardrailResult(BaseModel):
    model_config = _STRICT
    passed: bool
    checks: list[ClaimCheck] = Field(default_factory=list)


# ── Planner I/O ───────────────────────────────────────────────────────────────
# The LLM picks layouts + titles (no slide numbers); the manager node maps each
# choice to its real template slide via slot_map and enforces uniqueness. Keeping
# slide-number assignment OUT of the LLM avoids a whole class of hallucinated ids.
class PlannerChoice(BaseModel):
    model_config = _STRICT
    layout_id: str                    # must be a selectable id from slot_map
    title: str
    kind: Literal["data", "narrative"]


class PlannerOutput(BaseModel):
    model_config = _STRICT
    deck_title: str
    slides: list[PlannerChoice] = Field(min_length=1, max_length=11)