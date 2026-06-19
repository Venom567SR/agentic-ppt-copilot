"""
ai/agents_prompts/deck_writer.py -- (3) per-slot content reasoner -> SlotContent (Gemini 3.1 Pro)

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.deck_writer import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\
TODO: write the system prompt for the deck_writer node.
"""

system_prompt = system_prompt_v1
