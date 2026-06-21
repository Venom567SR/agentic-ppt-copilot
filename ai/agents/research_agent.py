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
        corpus_map = state.get("corpus_map")
        if corpus_map:
            msg += ("\n\nThe user attached source documents. Here is what they "
                    "contain (do NOT ask for anything these already cover):\n" + corpus_map)
        elif state.get("user_files"):
            msg += (f"\n\nThe user also attached {len(state['user_files'])} document(s) as "
                    f"source material; factor that in when deciding what still needs clarifying.")
        return msg


_agent = ResearchAgent()


def node(state: GraphState) -> dict:
    """LangGraph node: generate clarifying questions, pause for the user at gate 1.
    If the supervisor flagged a scope ambiguity, ask that too."""
    result = _agent.run(state)
    questions = list(result.questions)
    scope_q = state.get("scope_question")
    if scope_q and scope_q not in questions:
        questions.append(scope_q)
    return {
        "clarifying_questions": questions,
        "status": "awaiting_clarification",
    }