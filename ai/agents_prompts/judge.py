"""
ai/agents_prompts/judge.py -- (5) grounding judge (DeepEval Faithfulness, Gemini 3.5 Flash)

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.judge import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\
TODO: write the system prompt for the judge node.
"""

system_prompt = system_prompt_v1
