"""
ai/agents/supervisor.py -- the routing brain (structured graph + supervisor)

Two responsibilities:

1. JUDGMENT (LLM): `ScopeRouter` decides whether the data scope is ambiguous
   enough to ask the user (e.g. uploaded org-specific data vs an industry-wide
   topic). This is the one genuinely "agentic" routing decision -- a rule can't
   reliably tell "insurance sector in India" (industry-wide) from "our insurance
   performance" (internal), but a model can, and when unsure it asks.

2. RULES (deterministic): the `route_*` functions are pure functions of state
   that graph/build.py wires onto conditional edges. They return a label; build.py
   maps each label to the next node. Keeping them here (not buried in build.py)
   makes the routing policy inspectable in one place.

Routing contract (labels build.py maps to nodes):
  route_after_intent -> "block" | "ingest" | "clarify"
  route_after_plan   -> "curate" | "write"
  route_after_judge  -> "repair" | "render"
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.supervisor import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import ScopeDecision
from ai.graph.state import GraphState
from ai.src.logger import get_logger

logger = get_logger(__name__)


# ── judgment: scope ambiguity (LLM) ─────────────────────────────────────────────
class ScopeRouter(BaseAgent[ScopeDecision]):
    task = "supervisor"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = ScopeDecision
    temperature = 0.0                       # a stable judgment, not creative

    def build_user_message(self, state: GraphState) -> str:
        return (f"Topic:\n{state['query']}\n\n"
                f"{state.get('corpus_map') or '(no documents)'}\n\n"
                f"Decide whether the data scope is ambiguous.")


_scope_agent = ScopeRouter()


def scope_node(state: GraphState) -> dict:
    """Supervisor node: when files are present, judge scope ambiguity. If ambiguous,
    surface ONE scope question for the clarifier to ask at gate 1. Otherwise pass
    through. LLM failure degrades to 'no scope question' (never blocks the run)."""
    if not state.get("corpus_map"):
        return {}
    try:
        decision = _scope_agent.run(state)
    except Exception as e:
        logger.warning("[supervisor] scope check failed (%s); proceeding without it", e)
        return {}
    if decision.ambiguous and decision.question:
        logger.info("[supervisor] scope ambiguous -> ask user: %s", decision.question)
        return {"scope_question": decision.question}
    return {}


# ── rules: deterministic routing (pure functions of state) ───────────────────────
def route_after_intent(state: GraphState) -> str:
    """block on a rejected intent; ingest files first if present; else clarify."""
    intent = state.get("intent")
    if intent is not None and intent.verdict == "block":
        return "block"
    return "ingest" if state.get("user_files") else "clarify"


def route_after_plan(state: GraphState) -> str:
    """Curate user-file evidence (needs the approved plan as the agenda) before
    writing, when files were provided; otherwise write straight away."""
    return "curate" if state.get("user_files") else "write"


def route_after_judge(state: GraphState) -> str:
    """Repair if any data slide failed grounding; else proceed to render."""
    guardrail = state.get("guardrail") or {}
    any_failed = any(not r.passed for r in guardrail.values())
    return "repair" if any_failed else "render"