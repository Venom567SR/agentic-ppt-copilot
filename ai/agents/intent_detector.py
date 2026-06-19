"""
ai/agents/intent_detector.py -- (1) guard: harm/intent filter (Gemini 3.1 Flash-Lite)

Thin BaseAgent subclass + a LangGraph node adapter. The class does the reasoning;
node(state) adapts the verdict into a GraphState update and sets `status`.
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.intent_detector import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import IntentVerdict
from ai.graph.state import GraphState


class IntentDetector(BaseAgent[IntentVerdict]):
    task = "intent_detector"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = IntentVerdict
    temperature = 0.0                       # deterministic guard

    def build_user_message(self, state: GraphState) -> str:
        return f"Topic to evaluate:\n{state['query']}"


_agent = IntentDetector()


def node(state: GraphState) -> dict:
    """LangGraph node: run the guard, update state + control status."""
    verdict = _agent.run(state)
    return {
        "intent": verdict,
        "status": "blocked" if verdict.verdict == "block" else "running",
    }