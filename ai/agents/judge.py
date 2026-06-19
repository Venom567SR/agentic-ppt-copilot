"""
ai/agents/judge.py
(5) grounding judge (DeepEval Faithfulness, Gemini 3.5 Flash)
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.judge import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class Judge(BaseAgent):
    task = "judge"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
