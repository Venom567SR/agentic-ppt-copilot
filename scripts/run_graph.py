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
import uuid

from ai.graph.build import build_graph
from ai.agents.context_retriever import release


def _print_plan(plan) -> None:
    print(f"\nPLAN: {plan.deck_title}")
    for s in plan.slides:
        print(f"  slide {s.slide:>2}  {s.layout_id:<18} [{s.kind}]  {s.title}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="presentation topic")
    ap.add_argument("--files", nargs="*", default=[], help="up to 3 source files")
    args = ap.parse_args()

    tid = uuid.uuid4().hex
    config = {"configurable": {"thread_id": tid}}
    app = build_graph()

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
            answers[q] = input(f"Q: {q}\n> ").strip()
        app.update_state(config, {"clarification_answers": answers})

        # ── run to gate 2 (after manager) ──
        app.invoke(None, config)
        state = app.get_state(config).values
        _print_plan(state["plan"])

        # ── HITL gate 2: plan approval ──
        if input("\nApprove this plan? [y/N] ").strip().lower() != "y":
            print("Plan rejected -- aborting run.")
            return

        # ── run to completion (curate -> write -> images -> judge -> [repair] -> visual_qa -> render) ──
        print("\nGenerating deck (this calls the writer/judge per slide)...")
        app.invoke(None, config)
        state = app.get_state(config).values

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


if __name__ == "__main__":
    main()