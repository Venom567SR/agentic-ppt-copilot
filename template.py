#!/usr/bin/env python3
"""
template.py — PPT_GEN scaffold generator
========================================
Creates the full project tree (dirs, __init__.py, stub files) in one run.

Idempotent: it NEVER overwrites an existing file — it only creates what is
missing. Safe to run over your current partial scaffold, and safe to re-run.

Usage:
    python template.py          # scaffold into the current directory
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
PACKAGES = [  # get an __init__.py
    "ai", "ai/agents", "ai/agents_prompts", "ai/graph",
    "ai/rendering", "ai/tools", "ai/src", "ai/utils", "backend",
]
PLAIN_DIRS = ["assets", "outputs", "runs", "frontend", "tests", "tests/eval"]

# ---------------------------------------------------------------------------
# Agents (LLM reasoning nodes) — name: role
# ---------------------------------------------------------------------------
AGENTS = {
    "intent_detector":  "(1) guard: harm/intent filter (Gemini 3.1 Flash-Lite)",
    "research_agent":   "(1) clarifier: clarifying questions (Gemini 3 Flash) -- HITL gate 1",
    "manager":          "(2) classifier + outline planner -> DeckPlan (Gemini 3 Flash / 3.1 Pro) -- HITL gate 2",
    "context_retriever":"(3) grounding from user-uploaded documents (optional)",
    "web_search":       "(3) Tavily grounding + provenance",
    "deck_writer":      "(3) per-slot content reasoner -> SlotContent (Gemini 3.1 Pro)",
    "image_generator":  "(3) visual planner -> ImageSpec, then Nano Banana generation",
    "judge":            "(5) grounding judge (DeepEval Faithfulness, Gemini 3.5 Flash)",
}


# ---------------------------------------------------------------------------
# Stub generators
# ---------------------------------------------------------------------------
def _class_name(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def agent_stub(name: str, role: str) -> str:
    cls = _class_name(name)
    return f'''"""
ai/agents/{name}.py
{role}
"""
from ai.agents.base import BaseAgent
from ai.agents_prompts.{name} import system_prompt, VERSION
# from ai.schemas import <OutputModel>


class {cls}(BaseAgent):
    task = "{name}"                 # routing key into get_llm() + config.yaml
    system_prompt = system_prompt
    prompt_version = VERSION
    # output_schema = <OutputModel>  # Pydantic model this node must return

    def build_user_message(self, state) -> str:
        raise NotImplementedError  # TODO: derive the user content from GraphState
'''


def prompt_stub(name: str, role: str) -> str:
    return f'''"""
ai/agents_prompts/{name}.py -- {role}

Prompts-as-code: `system_prompt` is the current-version pointer.
Keep old versions as system_prompt_vN; nodes log VERSION for traceability.
Import:  from ai.agents_prompts.{name} import system_prompt, VERSION
"""

VERSION = "v1"

system_prompt_v1 = """\\
TODO: write the system prompt for the {name} node.
"""

system_prompt = system_prompt_v1
'''


def header(path: str, role: str) -> str:
    return f'"""\\n{path}\\n{role}\\n\\nTODO: implement.\\n"""\\n'


# ---------------------------------------------------------------------------
# Explicit file contents
# ---------------------------------------------------------------------------
FILES: dict[str, str] = {}

# --- ai core ---
FILES["ai/llm.py"] = '''"""
ai/llm.py -- LLM factory + per-task model routing.

get_llm(task) returns a configured client. The task->model map lives in
config.yaml so routing is config, not code. Backend (Vertex vs Developer API)
is an env switch (USE_VERTEX), mirroring the prior project's pattern.
"""
# from ai.config_env import settings


def get_llm(task: str, temperature: float = 0.3):
    """Return an LLM client for the given task key (see config.yaml model_routing)."""
    raise NotImplementedError  # TODO
'''

FILES["ai/config.yaml"] = '''# Central configuration -- models, slot capacities, brand tokens, paths.

template_path: assets/ICICI_PRU_AMC_PPT_Format.pptx

model_routing:
  intent_detector:   gemini-3.1-flash-lite
  research_agent:    gemini-3-flash
  manager:           gemini-3.1-pro
  context_retriever: gemini-3-flash
  web_search:        gemini-3-flash
  deck_writer:       gemini-3.1-pro
  image_generator:   gemini-3.1-pro       # visual PLANNING (reasoning); generation uses the image model
  image_model:       gemini-2.5-flash-image
  judge:             gemini-3.5-flash

brand:
  fonts:   { header: "Mulish ExtraBold", body: "Mulish SemiBold" }
  primary: { orange: "DB620A", maroon: "97291E", navy: "053C6D", beige: "D1CFBB" }
  secondary: { purple: "917BB9", gold: "FDB92A", pink: "F4858E", cyan: "00C0F3" }

# Per-slot capacities are authored in ai/rendering/slot_map.py (derived from the
# real template) and consumed by fit_validator.py.
'''

FILES["ai/config_env.py"] = '''"""
ai/config_env.py -- load .env (secrets, flags) and parse config.yaml into one
settings object the rest of the app imports.
"""
# import os, yaml
# from dotenv import load_dotenv

# load_dotenv()
# TODO: expose a `settings` object (api keys, USE_VERTEX, parsed config.yaml)
'''

FILES["ai/schemas.py"] = '''"""
ai/schemas.py -- the central Pydantic v2 contract.

These objects flow through GraphState and into the renderer. Fit limits live on
the fields (e.g. Field(max_length=...)) so validation enforces template fit.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class Source(BaseModel):
    url: str
    title: str
    retrieved_at: datetime
    claim_supported: str = ""
    authority: Literal["user_file", "web", "none"] = "web"  # ranks evidence; file wins on conflict


class SlotContent(BaseModel):
    lines: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class ImageSpec(BaseModel):
    depict: str
    style_prefix: str
    aspect_ratio: str
    safety: Literal["ok", "blocked"] = "ok"
    fallback_angle: str | None = None


class SlideContent(BaseModel):
    layout_id: str
    slots: dict[str, SlotContent] = Field(default_factory=dict)
    image: ImageSpec | None = None


class DeckPlan(BaseModel):
    title: str
    slides: list[dict] = Field(default_factory=list)  # (layout_id, title, kind: data|narrative)


class FallbackDecision(BaseModel):
    rung: Literal["image", "qualitative", "rewrite", "drop"]
    reason: str


# TODO: GraphState (accumulates all of the above across nodes)
'''

# --- agents ---
FILES["ai/agents/base.py"] = '''"""
ai/agents/base.py -- BaseAgent: the shared reasoning-node loop.

Every LLM node subclasses this. It owns: load prompt -> route to get_llm(task)
-> call with structured output -> validate into output_schema -> retry once on
ValidationError -> log VERSION + token usage. This is what makes
"each node emits a typed object" an enforced contract, not a convention.

NOTE: ppt_generator is deliberately NOT a BaseAgent -- it is the deterministic
renderer driver and makes no LLM call.
"""
from __future__ import annotations
from typing import Generic, TypeVar

OutT = TypeVar("OutT")


class BaseAgent(Generic[OutT]):
    task: str
    system_prompt: str
    prompt_version: str
    output_schema: type

    def build_user_message(self, state) -> str:
        raise NotImplementedError

    def run(self, state) -> "OutT":
        # 1) messages = [system_prompt, build_user_message(state)]
        # 2) call get_llm(self.task) with response_schema=output_schema
        # 3) parse -> validate into output_schema
        # 4) on ValidationError: one tighter retry, then raise custom_exception
        # 5) log self.prompt_version, self.task, token usage
        raise NotImplementedError  # TODO
'''

FILES["ai/agents/ppt_generator.py"] = '''"""
ai/agents/ppt_generator.py -- (4) renderer driver. NOT a BaseAgent (no LLM).

Consumes the finalized SlideContent objects and calls ai/rendering/ to write
them into the per-run unpacked template, then repacks. Pure orchestration of
deterministic steps.
"""
# from ai.rendering import template_renderer, slot_map, pptx_io, workspace


def render_deck(state) -> str:
    """Apply approved content to the template; return path to the packed .pptx."""
    raise NotImplementedError  # TODO
'''

# --- graph ---
FILES["ai/graph/state.py"] = header("ai/graph/state.py", "GraphState: shared state accumulating each node's typed decision.")
FILES["ai/graph/build.py"] = header("ai/graph/build.py", "StateGraph wiring: nodes, conditional edges, checkpointer, interrupt() gates.")
FILES["ai/graph/routing.py"] = header("ai/graph/routing.py", "Conditional-edge functions: region type, search result, degradation ladder.")

# --- rendering ---
FILES["ai/rendering/template_renderer.py"] = (
    '"""\\nai/rendering/template_renderer.py\\n\\n'
    'REPLACE THIS STUB with the validated renderer deliverable (set_shape_lines /\\n'
    'set_table / set_smartart_full / swap_image). Already built and QA-passed.\\n"""\\n'
)
FILES["ai/rendering/slot_map.py"] = header("ai/rendering/slot_map.py", "Per-slide editable-slot registry (the layout library). Generated against the real template.")
FILES["ai/rendering/pptx_io.py"] = header("ai/rendering/pptx_io.py", "unpack() / pack() wrappers around the OOXML tree.")
FILES["ai/rendering/image_fit.py"] = header("ai/rendering/image_fit.py", "Pillow resize/crop of a generated image to an exact bbox.")
FILES["ai/rendering/fit_validator.py"] = header("ai/rendering/fit_validator.py", "Deterministic char/bullet/row capacity checks against slot_map (bold cells use a wider budget).")
FILES["ai/rendering/workspace.py"] = '''"""
ai/rendering/workspace.py -- per-run scratch isolation keyed by thread_id.

make_run_dir(thread_id) creates runs/<id>/{unpacked,gen,media_fitted} and copies
the template into unpacked/ so assets/ is never mutated. cleanup(thread_id) sweeps
scratch, optionally keeping deck.pptx. Prevents cross-run media collisions.
"""
# from pathlib import Path
# import shutil


def make_run_dir(thread_id: str):
    raise NotImplementedError  # TODO


def cleanup(thread_id: str, keep_output: bool = True) -> None:
    raise NotImplementedError  # TODO
'''

# --- tools ---
FILES["ai/tools/tavily_client.py"] = header("ai/tools/tavily_client.py", "Tavily search wrapper -- returns results + source URLs for provenance.")
FILES["ai/tools/gemini_image.py"] = header("ai/tools/gemini_image.py", "Nano Banana (Gemini image) wrapper with aspect-ratio hinting.")

# --- src / utils ---
FILES["ai/src/logger.py"] = header("ai/src/logger.py", "Project logger (UTF-8 safe, rotating).")
FILES["ai/src/custom_exception.py"] = header("ai/src/custom_exception.py", "Custom exception classes.")
FILES["ai/utils/provenance.py"] = header("ai/utils/provenance.py", "Assemble sources -> chat citations panel + durable per-slide speaker notes.")

# --- backend ---
FILES["backend/main.py"] = '''"""
backend/main.py -- FastAPI service (thin wrapper over ai/).

Resumable HITL contract:
    POST /generate         -> start; returns {status, thread_id, question?}
    POST /resume           -> answer a gate; re-enters the graph at its checkpoint
    GET  /result/{thread_id} -> returns the .pptx + per-slide citations
"""
# from fastapi import FastAPI
# app = FastAPI()
# TODO: wire endpoints to ai.graph.build
'''

# --- root files ---
FILES[".env.example"] = '''USE_VERTEX="true"

# --- Vertex AI (when USE_VERTEX=true). Requires: gcloud auth application-default login ---
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
GOOGLE_CLOUD_LOCATION="us-central1"

# --- Key-based services (not on Vertex) ---
TAVILY_API_KEY=
'''

FILES[".gitignore"] = '''.venv/
__pycache__/
*.pyc
.env
outputs/
runs/
'''

FILES["requirements.txt"] = '''langgraph
langchain
google-genai
pydantic>=2
python-pptx
lxml
Pillow
tavily-python
deepeval
fastapi
uvicorn
python-dotenv
pyyaml
matplotlib
'''

FILES["README.md"] = '''# PPT_GEN -- Brand-Faithful Presentation Generator

Agentic copilot that fills the ICICI Prudential AMC brand template with
topic-specific content **in place** (XML-level), preserving structure, colours,
fonts, swooshes and logo. See `project_structure.md` and `architecture_flow.md`.

## Layout
- `ai/`        interface-agnostic core (graph, agents, rendering, schemas)
- `backend/`   FastAPI wrapper (resumable HITL: /generate, /resume, /result)
- `frontend/`  client (Antigravity / Claude Design)

## Run scaffold
    python template.py
'''


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------
def write(rel_path: str, content: str) -> None:
    p = ROOT / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        print(f"  skip (exists): {rel_path}")
        return
    p.write_text(content, encoding="utf-8")
    print(f"  created:       {rel_path}")


def main() -> None:
    print("Scaffolding PPT_GEN ...")

    for d in PLAIN_DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    for pkg in PACKAGES:
        (ROOT / pkg).mkdir(parents=True, exist_ok=True)
        write(f"{pkg}/__init__.py", "")

    # agents + their prompt modules
    for name, role in AGENTS.items():
        write(f"ai/agents/{name}.py", agent_stub(name, role))
        write(f"ai/agents_prompts/{name}.py", prompt_stub(name, role))

    # everything else
    for rel_path, content in FILES.items():
        write(rel_path, content)

    # keep empty dirs in git
    for d in ["outputs", "runs", "assets", "tests/eval", "frontend"]:
        write(f"{d}/.gitkeep", "")

    print("Done. (Re-runnable; existing files are never overwritten.)")


if __name__ == "__main__":
    main()