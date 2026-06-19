"""
ai/agents/base.py
=================
BaseAgent — the shared loop every reasoning node sits on.

Each subclass declares: task (routing key), system_prompt (+ prompt_version),
output_schema (the Pydantic type it must return), and build_user_message(state).

run() binds the schema via get_structured_llm, invokes, and on a bad/invalid
response does exactly ONE corrective retry, then raises a traceable AgentError.
No silent fallback, no loop. Every call logs task + prompt_version so any output
traces back to the exact prompt that produced it.

ppt_generator is intentionally NOT a BaseAgent (it makes no LLM call).
"""
from __future__ import annotations

import time
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ai.src.logger import get_logger
from ai.src.custom_exception import AgentError

logger = get_logger(__name__)

OutT = TypeVar("OutT", bound=BaseModel)


class BaseAgent(Generic[OutT]):
    task: str                      # routing key -> get_structured_llm + config.yaml
    system_prompt: str             # from ai.agents_prompts.<name>
    prompt_version: str
    output_schema: type[OutT]
    temperature: float = 0.2

    # --- subclasses implement this ---
    def build_user_message(self, state) -> str:
        raise NotImplementedError

    # --- overridable for testing (lazy import keeps base.py importable w/o the LLM stack) ---
    def _get_llm(self):
        from ai.llm import get_structured_llm
        return get_structured_llm(self.task, self.output_schema, self.temperature)

    def _messages(self, state, extra: str | None = None):
        msgs = [("system", self.system_prompt),
                ("user", self.build_user_message(state))]
        if extra:
            msgs.append(("user", extra))
        return msgs

    def run(self, state) -> OutT:
        llm = self._get_llm()
        t0 = time.perf_counter()
        try:
            result = llm.invoke(self._messages(state))
            if result is None:
                raise ValueError("structured output returned None")
        except (ValidationError, ValueError) as e:
            logger.warning("[%s %s] invalid output, one retry: %s",
                           self.task, self.prompt_version, e)
            try:
                result = llm.invoke(self._messages(
                    state, extra="Return ONLY data that exactly matches the required "
                                 "schema. Do not add fields. Do not include commentary."))
                if result is None:
                    raise ValueError("structured output returned None on retry")
            except Exception as e2:
                raise AgentError(self.task,
                                 f"schema validation failed after retry: {e2}", cause=e2)
        except Exception as e:
            raise AgentError(self.task, f"LLM call failed: {e}", cause=e)

        dt = (time.perf_counter() - t0) * 1000
        logger.info("[%s %s] ok in %.0fms -> %s",
                    self.task, self.prompt_version, dt, type(result).__name__)
        return result