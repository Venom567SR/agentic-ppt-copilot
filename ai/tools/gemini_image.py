"""
ai/tools/gemini_image.py
========================
Nano Banana (Gemini image) wrapper for NARRATIVE illustrations -- used when a
slide's visual region should hold a depictive image (e.g. a Dandi March scene)
rather than a data chart. Uses the google-genai SDK; backend follows USE_VERTEX.

Data chart-image regions do NOT use this -- they use ai/rendering/chart_render.py.
"""
from __future__ import annotations

from pathlib import Path

from ai.config_env import settings
from ai.src.logger import get_logger

logger = get_logger(__name__)

_IMAGE_MODEL_KEY = "image_model"  # resolved from config.yaml model_routing


def _client():
    from google import genai
    if settings.use_vertex:
        return genai.Client(vertexai=True, project=settings.gcp_project,
                            location=settings.gcp_location)
    return genai.Client(api_key=settings.gemini_api_key)


def generate_image(prompt: str, out_path: str | Path) -> Path:
    """Generate one image from a (brand-prefixed) prompt; save to out_path."""
    out_path = Path(out_path)
    model_id = settings.model_routing.get(_IMAGE_MODEL_KEY, "gemini-2.5-flash-image")
    logger.info("Image gen via %s -> %s", model_id, out_path.name)

    client = _client()
    resp = client.models.generate_content(model=model_id, contents=prompt)
    # google-genai returns inline image parts; grab the first image blob.
    for part in resp.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            out_path.write_bytes(inline.data)
            return out_path
    raise RuntimeError("image model returned no image data")