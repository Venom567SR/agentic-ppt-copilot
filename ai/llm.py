"""
ai/llm.py
=========
LLM factory. Uses langchain-google-genai 4.0+ (ChatGoogleGenerativeAI), which
supersedes the deprecated langchain-google-vertexai ChatVertexAI and runs on the
consolidated google-genai SDK.

Routing (task -> model id) lives in config.yaml, so swapping a model is a one-line
config edit. Backend is selected by USE_VERTEX:
  * Vertex AI  (USE_VERTEX=true):  project + vertexai=True -> ADC. No api_key.
  * Gemini API (USE_VERTEX=false): GEMINI_API_KEY.

Text/reasoning models only; image generation uses ai/tools/gemini_image.py.

    from ai.llm import get_structured_llm
    from ai.schemas import IntentVerdict
    llm = get_structured_llm("intent_detector", IntentVerdict)
    verdict = llm.invoke([("system", system_prompt), ("user", query)])  # -> IntentVerdict
"""
from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from ai.config_env import settings
from ai.src.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=None)
def _client(model_id: str, temperature: float) -> ChatGoogleGenerativeAI:
    if settings.use_vertex:
        if not settings.gcp_project:
            raise ValueError("USE_VERTEX=true requires GOOGLE_CLOUD_PROJECT in .env")
        logger.info("LLM via Vertex AI: model=%s temp=%s project=%s location=%s",
                    model_id, temperature, settings.gcp_project, settings.gcp_location)
        # NOTE: no api_key on the Vertex path (api_key + vertexai=True is a known bug).
        return ChatGoogleGenerativeAI(
            model=model_id,
            temperature=temperature,
            project=settings.gcp_project,
            location=settings.gcp_location,
            vertexai=True,
        )
    # Developer API fallback
    if not settings.gemini_api_key:
        raise ValueError("USE_VERTEX=false requires GEMINI_API_KEY in .env")
    logger.info("LLM via Gemini Developer API: model=%s temp=%s", model_id, temperature)
    return ChatGoogleGenerativeAI(
        model=model_id,
        temperature=temperature,
        api_key=settings.gemini_api_key,
    )


def model_for(task: str) -> str:
    model_id = settings.model_routing.get(task)
    if not model_id:
        raise KeyError(f"No model configured for task '{task}' under model_routing in config.yaml.")
    return model_id


def get_llm(task: str, temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    """Raw chat client for a task (free-form output)."""
    return _client(model_for(task), temperature)


def get_structured_llm(task: str, schema, temperature: float = 0.2):
    """Chat client bound to a Pydantic schema (native controlled generation).

    .invoke(...) returns a validated `schema` instance. Lower default temperature
    for determinism on structured/factual nodes.
    """
    return get_llm(task, temperature).with_structured_output(schema)