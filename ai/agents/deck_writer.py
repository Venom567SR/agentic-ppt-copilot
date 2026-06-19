"""
ai/agents/deck_writer.py
(3) per-slot content reasoner -> SlotContent (Gemini 3.1 Pro)
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.deck_writer import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class DeckWriter(BaseAgent):
    task = "deck_writer"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
