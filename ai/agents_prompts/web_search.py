"""
ai/agents_prompts/web_search.py -- (3) Tavily grounding + provenance

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.web_search import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\
TODO: write the system prompt for the web_search node.
"""

system_prompt = system_prompt_v1
