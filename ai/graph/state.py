"""
ai/graph/state.py
=================
GraphState — the shared state threaded through the LangGraph run.

TypedDict (not a BaseModel) because LangGraph merges partial updates by key:
each node returns ONLY the fields it changed, and the graph merges them. The
*values* are validated Pydantic models from ai.schemas, so we keep validation
where it matters (the decision objects) and idiomatic merging where it matters
(the state container).

Accumulating fields use Annotated[..., operator.add] reducers, so e.g. every
node can append a warning or a source without clobbering earlier ones — which
makes a run trivial to trace: the final state holds the full audit trail.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from ai.schemas import (             # repo import
    IntentVerdict, DeckPlan, SlideContent, Source, FallbackDecision, GuardrailResult,
)

Status = Literal[
    "running",
    "awaiting_clarification",   # HITL gate 1
    "awaiting_approval",        # HITL gate 2
    "awaiting_data",            # HITL gate 3 (batched data questions)
    "blocked",                  # intent guard rejected
    "done",
]


class GraphState(TypedDict, total=False):
    # ── inputs ──
    thread_id: str
    query: str
    user_files: list[str]                       # uploaded docs = ground truth

    # ── user-file grounding (context_retriever) ──
    corpus_map: str                             # compact map -> clarifier / manager
    curated_evidence: str                       # curated verbatim user_file evidence
    scope_question: str                         # supervisor -> extra clarifying question

    # ── control (drives the HITL interrupt/resume contract) ──
    status: Status

    # ── phase outputs ──
    intent: IntentVerdict                       # (1) guard
    clarifying_questions: list[str]             # (1) clarifier -> gate 1
    clarification_answers: dict[str, str]       # user reply at gate 1
    plan: DeckPlan                              # (2) planner -> gate 2
    slides: list[SlideContent]                  # (3) content (set wholesale)
    evidence_by_slide: dict[int, str]           # (3) web evidence per data slide -> judge
    guardrail: dict[int, GuardrailResult]       # (4) grounding result per slide
    deck_path: str                              # (4) rendered deck
    citations: str                              # (5) assembled citations panel

    # ── accumulators (each node appends its delta) ──
    sources: Annotated[list[Source], operator.add]
    fallbacks: Annotated[list[FallbackDecision], operator.add]
    warnings: Annotated[list[str], operator.add]