"""
ai/agents/image_generator.py
(3) visual planner -> ImageSpec, then Nano Banana generation
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.image_generator import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class ImageGenerator(BaseAgent):
    task = "image_generator"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
