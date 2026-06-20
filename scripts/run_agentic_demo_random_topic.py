"""
scripts/run_agentic_demo_random_topic.py
=========================================
Same pipeline as run_agentic_demo, but topic is configurable to exercise the
NARRATIVE path (no charts; bullets + smartart). Useful to see how the planner and
writer behave on a non-financial topic.

Usage:
    python -m scripts.run_agentic_demo_random_topic
    python -m scripts.run_agentic_demo_random_topic "History of the Indian Railways"

Note: narrative layouts (bullets/smartart) have no image region in the template,
so a fully-narrative deck currently gets NO generated illustrations -- this run is
exactly what demonstrates that gap (the narrative-image routing we have yet to wire).
"""
import sys
from datetime import date

from ai.agents.manager import _agent as manager, _to_plan
from ai.agents.deck_writer import node as write_node
from ai.agents.image_generator import node as image_node
from ai.agents.ppt_generator import render_deck
from ai.config_env import settings

TOPIC = sys.argv[1] if len(sys.argv) > 1 else (
    "How Gandhi's Satyagraha movement helped India gain independence")
CLARIFICATIONS = ("For a college history class; about 8 slides; narrative overview "
                  "covering key campaigns, methods, and their impact on independence.")

# 1) PLAN -------------------------------------------------------------------
plan = _to_plan(manager.run({"query": TOPIC, "clarification_answers": CLARIFICATIONS}))
print(f"\nTOPIC: {TOPIC}")
print(f"PLAN: {plan.deck_title}")
for s in plan.slides:
    print(f"  slide {s.slide:>2}  {s.layout_id:<20} [{s.kind}]  {s.title}")

# 2) WRITE CONTENT (data slides are search-grounded) ------------------------
state = {"query": TOPIC, "clarification_answers": CLARIFICATIONS, "plan": plan}
slides = write_node(state)["slides"]
print(f"\nWrote {len(slides)} content slides.")

# 2b) VISUALS (charts for any data chart-slides; narrative slides get none yet)
state["slides"] = slides
slides = image_node(state)["slides"]
print("Visual pass complete.")

# 3) ASSEMBLE + RENDER ------------------------------------------------------
title_spec = {"slide": 1, "layout_id": "title",
              "text": {"title": [plan.deck_title], "subtitle": ["An Overview"],
                       "date": [date.today().strftime("%B %d, %Y")]}}
thankyou_spec = {"slide": 16, "layout_id": "thankyou", "text": {"closing": ["Thank you"]}}
specs = [title_spec] + [s.to_render_spec() for s in slides] + [thankyou_spec]

deck, warnings = render_deck(specs, "agentic_demo_random", settings.template_path,
                             deck_title=plan.deck_title)
print(f"\nDECK: {deck}")
print("WARNINGS:", warnings if warnings else "none")