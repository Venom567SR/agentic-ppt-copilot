"""
ai/config_env.py
================
Single source of truth: loads .env (secrets, flags) + config.yaml (routing,
brand, paths) into one `settings` object.

    from ai.config_env import settings
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().strip('"').lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    use_vertex: bool
    gcp_project: str | None
    gcp_location: str
    gemini_api_key: str | None          # used only when USE_VERTEX=false
    tavily_api_key: str | None
    template_path: str
    model_routing: dict[str, str] = field(default_factory=dict)
    brand: dict = field(default_factory=dict)


def _load() -> Settings:
    cfg = yaml.safe_load(_CONFIG_PATH.read_text()) if _CONFIG_PATH.exists() else {}
    cfg = cfg or {}
    return Settings(
        use_vertex=_bool(os.getenv("USE_VERTEX"), default=True),
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        gcp_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        template_path=cfg.get("template_path", "assets/ICICI_PRU_AMC_PPT_Format.pptx"),
        model_routing=cfg.get("model_routing", {}),
        brand=cfg.get("brand", {}),
    )


settings = _load()