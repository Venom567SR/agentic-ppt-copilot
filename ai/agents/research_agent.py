"""
ai/agents/research_agent.py -- (1) clarifier (Gemini 2.5 Flash) -> HITL gate 1

Produces adaptive clarifying questions, then the node flips the graph into the
gate-1 interrupt. The user's answers return via /resume into clarification_answers.
"""
from __future__ import annotations

from ai.agents.base import BaseAgent
from ai.agents_prompts.research_agent import system_prompt as SYSTEM_PROMPT, VERSION
from ai.schemas import ClarifyingQuestions
from ai.graph.state import GraphState


class ResearchAgent(BaseAgent[ClarifyingQuestions]):
    task = "research_agent"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = ClarifyingQuestions
    temperature = 0.4                       # a little variety in phrasing

    def build_user_message(self, state: GraphState) -> str:
        msg = f"Topic:\n{state['query']}"
        files = state.get("user_files") or []
        if files:
            msg += (f"\n\nThe user also attached {len(files)} document(s) as source "
                    f"material; factor that in when deciding what still needs clarifying.")
        return msg


_agent = ResearchAgent()


def node(state: GraphState) -> dict:
    """LangGraph node: generate clarifying questions, pause for the user at gate 1."""
    result = _agent.run(state)
    return {
        "clarifying_questions": result.questions,
        "status": "awaiting_clarification",
    }