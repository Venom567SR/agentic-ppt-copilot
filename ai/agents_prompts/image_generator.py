"""
ai/agents_prompts/image_generator.py -- (3) visual planner -> ImageSpec, then Nano Banana generation

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.image_generator import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\
TODO: write the system prompt for the image_generator node.
"""

system_prompt = system_prompt_v1
