"""
scripts/run_agentic_demo.py
===========================
First fully agent-generated deck: query -> plan -> content -> rendered .pptx.
(No grounding / no images yet — those agents come next. Tables/charts here use
model-written content; the guardrail + web_search will ground them later.)

Run from repo root:  python -m scripts.run_agentic_demo
"""
from datetime import date

from ai.agents.manager import _agent as manager, _to_plan
from ai.agents.deck_writer import node as write_node
from ai.agents.ppt_generator import render_deck
from ai.config_env import settings

QUERY = "Banking Sector in India"
CLARIFICATIONS = ("For executives; focus on growth and digital adoption; "
                  "current state plus 5-year outlook; high-level.")

# 1) PLAN (manager) ----------------------------------------------------------
plan = _to_plan(manager.run({"query": QUERY, "clarification_answers": CLARIFICATIONS}))
print(f"\nPLAN: {plan.deck_title}")
for s in plan.slides:
    print(f"  slide {s.slide:>2}  {s.layout_id:<20} [{s.kind}]  {s.title}")

# 2) WRITE CONTENT (deck_writer) --------------------------------------------
state = {"query": QUERY, "clarification_answers": CLARIFICATIONS, "plan": plan}
write_out = write_node(state)
slides = write_out["slides"]
state["evidence_by_slide"] = write_out["evidence_by_slide"]
print(f"\nWrote {len(slides)} content slides.")

# 2b) VISUALS (image_generator): real brand charts for data chart-slides --
from ai.agents.image_generator import node as image_node
state["slides"] = slides
slides = image_node(state)["slides"]
print("Generated visuals for chart-image slides.")

# 2c) GUARDRAIL (judge): verify data slides are grounded in evidence ------
from ai.agents.judge import node as judge_node
state["slides"] = slides
guard = judge_node(state)["guardrail"]
print("\nGrounding check:")
for sn, res in guard.items():
    flag = "PASS" if res.passed else "REVIEW"
    print(f"  slide {sn}: {flag} ({len(res.checks)} claims checked)")

# 3) ASSEMBLE bookends (title + thank-you) and RENDER -----------------------
title_spec = {
    "slide": 1, "layout_id": "title",
    "text": {"title": [plan.deck_title],
             "subtitle": ["Structure, Growth & Outlook"],
             "date": [date.today().strftime("%B %d, %Y")]},
}
thankyou_spec = {"slide": 16, "layout_id": "thankyou", "text": {"closing": ["Thank you"]}}

specs = [title_spec] + [s.to_render_spec() for s in slides] + [thankyou_spec]
deck, warnings = render_deck(specs, "agentic_demo", settings.template_path,
                             deck_title=plan.deck_title)

print(f"\nDECK: {deck}")
print("WARNINGS:", warnings if warnings else "none")