# PPT_GEN -- Brand-Faithful Presentation Generator

Agentic copilot that fills the ICICI Prudential AMC brand template with
topic-specific content **in place** (XML-level), preserving structure, colours,
fonts, swooshes and logo. See `project_structure.md` and `architecture_flow.md`.

## Layout
- `ai/`        interface-agnostic core (graph, agents, rendering, schemas)
- `backend/`   FastAPI wrapper (resumable HITL: /generate, /resume, /result)
- `frontend/`  client (Antigravity / Claude Design)

## Run scaffold
    python template.py
