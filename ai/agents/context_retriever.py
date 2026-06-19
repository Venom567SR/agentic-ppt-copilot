"""
ai/agents/context_retriever.py
(3) grounding from user-uploaded documents (optional)
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.context_retriever import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class ContextRetriever(BaseAgent):
    task = "context_retriever"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
