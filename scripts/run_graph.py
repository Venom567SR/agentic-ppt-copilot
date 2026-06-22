"""
scripts/run_graph.py -- drive a full agentic run from the terminal.

The graph pauses at two HITL gates (after `clarify`, after `manager`), so this
harness invokes, reads state at each pause, collects your input, and resumes.

Usage (from the activated .venv, repo root):
    python -m scripts.run_graph "Indian Banking Sector: Growth & Outlook" \
        --files "C:\\path\\one.pdf" "C:\\path\\two.xlsx"

    python -m scripts.run_graph "Mahatma Gandhi and the freedom struggle"   # no files
"""
from __future__ import annotations

import argparse
import os
import uuid

from ai.graph.build import build_graph
from ai.agents.context_retriever import release
from ai.rendering.slot_map import describe_layout
from ai.src.logger import attach_run_log, detach_run_log, write_slide_ordered_log
from ai.utils import provenance as prov


def _print_plan(plan) -> None:
    print(f"\nProposed deck: {plan.deck_title}")
    if getattr(plan, "subtitle", ""):
        print(f"({plan.subtitle})")
    print(f"{len(plan.slides)} content slides (plus a cover, agenda, and thank-you):")
    for i, s in enumerate(plan.slides, 1):
        print(f"  {i}. {s.title} — {describe_layout(s.layout_id)}")
    if getattr(plan, "note", ""):
        print(f"\nNote: {plan.note}")


def _print_summary(state) -> None:
    """A chat-style 'here's what I built' narration after generation: what the deck
    covers, which slides were verified against the user's files, what was softened,
    and the sources. (The technical RESULT block below keeps the raw detail.)"""
    plan = state.get("plan")
    guardrail = state.get("guardrail") or {}
    fallbacks = state.get("fallbacks") or []
    pos = {s.slide: (i, s.title) for i, s in enumerate(plan.slides, 1)} if plan else {}

    print("\n===== WHAT I BUILT =====")
    if plan:
        print(f'A {len(plan.slides)}-slide deck, "{plan.deck_title}", covering:')
        for i, s in enumerate(plan.slides, 1):
            print(f"  {i}. {s.title}")

    grounded = sorted(n for n, r in guardrail.items() if r.passed)
    if grounded:
        names = ", ".join(f'"{pos[n][1]}"' if n in pos else f"slide {n}" for n in grounded)
        nclaims = sum(len(guardrail[n].checks) for n in grounded)
        print(f"\nVerified against your files: {names} "
              f"— {nclaims} figures/claims traced back to the source data.")
    if fallbacks:
        print("\nA few claims weren't in your files, so I kept them qualitative rather "
              "than state them as fact:")
        for fb in fallbacks:
            print(f"  - {fb.reason}")

    files = sorted({os.path.basename(p.replace("\\", "/")) for p in (state.get("user_files") or [])})
    if files:
        print(f"\nGrounded in: {', '.join(files)}")
    print(f"\nSaved to: {state.get('deck_path')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="presentation topic")
    ap.add_argument("--files", nargs="*", default=[], help="up to 3 source files")
    args = ap.parse_args()

    tid = uuid.uuid4().hex
    config = {"configurable": {"thread_id": tid}}
    app = build_graph()
    run_log = attach_run_log(tid)   # JSON-lines file at runs/<tid>/run.log

    init = {"thread_id": tid, "query": args.query,
            "user_files": args.files, "status": "running"}

    try:
        # ── run to gate 1 (or END if the intent guard blocks) ──
        app.invoke(init, config)
        state = app.get_state(config).values

        if state.get("status") == "blocked":
            print("\nBLOCKED by intent guard:", state["intent"].reason)
            return

        if state.get("corpus_map"):
            print("\n--- corpus map (clarifier/manager saw this) ---")
            print(state["corpus_map"])

        # ── HITL gate 1: clarifying questions ──
        questions = state.get("clarifying_questions") or []
        print("\n===== CLARIFYING QUESTIONS =====")
        answers = {}
        for q in questions:
            print(f"Q: {q.question}")
            if q.suggestions:
                print(f"   (e.g. {' / '.join(q.suggestions)})")
            answers[q.question] = input("> ").strip()
        app.update_state(config, {"clarification_answers": answers})

        # ── run to gate 2 (after manager) ──
        app.invoke(None, config)

        # ── HITL gate 2: plan approval, with a revision loop ──
        while True:
            state = app.get_state(config).values
            _print_plan(state["plan"])
            ans = input("\nApprove this plan? Type 'y' to accept, or describe the "
                        "changes you want: ").strip()
            if ans.lower() in ("y", "yes"):
                app.update_state(config, {"plan_approved": True})
                print("\nGenerating deck (writer + judge per slide)...")
                app.invoke(None, config)
                break
            if not ans:
                continue
            print("Re-planning with your feedback...")
            app.update_state(config, {"plan_approved": False, "plan_feedback": ans})
            app.invoke(None, config)   # routes back to the manager, then pauses again

        state = app.get_state(config).values

        # ── user-facing summary (chat-style), then provenance, then technical detail ──
        _print_summary(state)

        record = prov.build_provenance(state)
        prov.print_table(record)
        prov.save(record, tid)

        # ── results ──
        print("\n===== RESULT =====")
        print("DECK:", state.get("deck_path"))

        guardrail = state.get("guardrail") or {}
        for slide_no, result in sorted(guardrail.items()):
            verdict = "PASS" if result.passed else "REVIEW"
            print(f"  grounding slide {slide_no}: {verdict} ({len(result.checks)} claims)")

        fallbacks = state.get("fallbacks") or []
        for fb in fallbacks:
            print(f"  repair: {fb.rung} -- {fb.reason}")

        warnings = state.get("warnings") or []
        if warnings:
            print("\nWARNINGS:")
            for w in warnings:
                print("  -", w)
    finally:
        release(tid)   # drop this session's curated corpus (temporary)
        by_slide = write_slide_ordered_log(run_log)
        detach_run_log(run_log)
        if by_slide:
            print(f"\n(Full run log: runs/{tid}/run.log · slide-ordered: {by_slide})")


if __name__ == "__main__":
    main()