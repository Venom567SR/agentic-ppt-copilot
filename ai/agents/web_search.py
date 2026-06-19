"""
ai/agents/web_search.py
(3) Tavily grounding + provenance
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.web_search import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class WebSearch(BaseAgent):
    task = "web_search"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
