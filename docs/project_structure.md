# Project Structure

A map of the repository and what each part is responsible for. The core (`ai/`) is
interface-agnostic; `backend/` and `frontend/` are thin layers over it.

```
agentic-ppt-copilot/
├── ai/                          # interface-agnostic core
│   ├── llm.py                   # LLM factory + per-task model routing (Vertex / Dev API)
│   ├── config_env.py            # settings: env flags, parsed config.yaml, brand tokens
│   ├── config.yaml              # model_routing, max_workers, brand palette, template path
│   ├── schemas.py               # central Pydantic contracts (typed objects through the graph)
│   │
│   ├── agents/                  # LLM reasoning nodes (each subclasses BaseAgent)
│   │   ├── base.py              # BaseAgent: prompt → call → validate → one retry → log
│   │   ├── intent_detector.py   # (1) harm / off-topic guard
│   │   ├── research_agent.py    # (1) clarifying questions  — HITL gate 1
│   │   ├── manager.py           # (2) classify + plan deck   — HITL gate 2
│   │   ├── supervisor.py        # scope-ambiguity judgment + deterministic routing fns
│   │   ├── context_retriever.py # ingest/curate user files (corpus, cap, dedup) — non-LLM ingest
│   │   ├── web_search.py        # (3) query planner + Tavily tool → evidence + sources
│   │   ├── deck_writer.py       # (3) per-slide content writer (concurrent)
│   │   ├── image_generator.py   # (3) chart / visual spec planner
│   │   ├── judge.py             # (4) faithfulness judge (concurrent)
│   │   └── ppt_generator.py     # (5) deterministic render driver (NOT a BaseAgent)
│   │
│   ├── agents_prompts/          # one prompt module per agent (prompts-as-code)
│   │   └── <agent>.py           # system_prompt_vN + active selector + derived VERSION
│   │
│   ├── rendering/               # deterministic OOXML editing (no LLM)
│   │   ├── slot_map.py          # editable-slot registry per layout (the "layout library")
│   │   ├── template_renderer.py # set text/table/SmartArt/chart in place
│   │   ├── fit_validator.py     # char/line/row capacity checks vs slot_map
│   │   ├── chart_render.py      # chart PNG generation/swap
│   │   ├── pptx_io.py           # unpack() / pack() the OOXML tree
│   │   └── workspace.py         # per-run scratch dir (template never mutated)
│   │
│   ├── tools/                   # external integrations
│   │   ├── tavily_client.py     # web search wrapper
│   │   ├── gemini_image.py      # image-model wrapper
│   │   └── doc_extract.py       # xlsx/docx/pdf/csv → text chunks
│   │
│   ├── graph/
│   │   ├── state.py             # GraphState (TypedDict accumulating each node's output)
│   │   └── build.py             # node + edge wiring, interrupts, checkpointer
│   │
│   ├── utils/
│   │   └── provenance.py        # claim → status → source record (pure logic) → JSON
│   │
│   └── src/
│       ├── logger.py            # two-sink logger (console + per-run JSON; slide-tagged)
│       └── custom_exception.py  # AgentError etc.
│
├── backend/
│   └── main.py                  # FastAPI: uploads, sessions, gates, generate, result, deck
│
├── frontend/
│   └── index.html               # single-file branded client (served by FastAPI at /)
│
├── scripts/
│   └── run_graph.py             # terminal HITL harness
│
├── smoke_test.py                # end-to-end HTTP walk of the backend
│
├── assets/                      # the brand template (read-only at runtime)
├── runs/                        # per-thread scratch + run.log + provenance.json
├── outputs/                     # generated decks
│
├── docs/
│   ├── architecture_flow.md     # design, the graph (Mermaid), node walkthrough
│   ├── project_structure.md     # this file
│   ├── img.png                  # architecture diagram (shown in README)
│   └── testing_docs/            # sample source files for end-to-end testing
│       └── *.csv / *.xlsx / *.pdf / *.docx
│
├── requirements.txt
└── .env.example                 # USE_VERTEX, GCP project/location, TAVILY_API_KEY
```

---

## Conventions

**Agent = reasoning, module = determinism.** Anything that calls an LLM is a `BaseAgent`
subclass with a paired prompt module. Anything deterministic (rendering, extraction,
provenance, fit-checking) is a plain module and makes no LLM call. `ppt_generator` is
deliberately *not* a BaseAgent — it is the render driver.

**Prompts-as-code, versioned.** Each `agents_prompts/<agent>.py` keeps every
`system_prompt_vN` intact, with an active selector line placed *after* all versions and a
`VERSION` derived from whichever prompt is active — so logs never mislabel an A/B run and
flipping one line switches versions safely.

**Typed contracts.** Nodes pass validated Pydantic objects via `GraphState`. Fit limits
live on the schema fields, so template-fit is enforced at validation time, not by hope.

**Per-task model routing.** `config.yaml:model_routing` maps each task → a Gemini 2.5
model; `llm.py` reads it. Routing is configuration, not code.

---

## Running it

```bash
# 1. install
pip install -r requirements.txt          # + python-multipart for uploads

# 2. auth (Vertex path)
#    set USE_VERTEX=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION in .env
gcloud auth application-default login
#    set TAVILY_API_KEY in .env

# 3a. terminal harness
python -m scripts.run_graph

# 3b. API + web UI
uvicorn backend.main:app --port 8000      # then open http://127.0.0.1:8000/

# 4. end-to-end smoke test (server must be running)
python smoke_test.py "Indian Banking Sector: Growth & Outlook" --files data1.xlsx data2.docx
```

See `docs/architecture_flow.md` for the design rationale and the graph diagram.