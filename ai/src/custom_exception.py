"""
ai/utils/custom_exception.py
============================
Typed exceptions so failures are loud and traceable (never silent fallbacks).
Each carries enough context to locate the failing node in logs.
"""
from __future__ import annotations


class PPTGenError(Exception):
    """Base class for all application errors."""


class AgentError(PPTGenError):
    """A reasoning node failed (LLM call or schema validation)."""

    def __init__(self, task: str, detail: str, cause: Exception | None = None):
        self.task = task
        self.detail = detail
        super().__init__(f"[{task}] {detail}")
        if cause is not None:
            self.__cause__ = cause


class RenderError(PPTGenError):
    """The deterministic renderer failed to apply content."""


class GroundingError(PPTGenError):
    """The output guardrail rejected content it could not ground."""