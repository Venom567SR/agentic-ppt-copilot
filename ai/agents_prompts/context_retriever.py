"""
ai/agents_prompts/context_retriever.py -- (3) grounding from user-uploaded documents (optional)

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.context_retriever import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\
TODO: write the system prompt for the context_retriever node.
"""

system_prompt = system_prompt_v1
