"""
backend/main.py -- FastAPI service over the agentic deck graph.

A thin ASYNC wrapper around the existing LangGraph state machine. The graph is the
source of truth; each endpoint resumes it at a checkpoint keyed by thread_id. The
sync graph is run via asyncio.to_thread so the event loop never blocks.

Flow (mirrors scripts/run_graph.py):
  POST /uploads                 stage files (per upload_id), return ids
  POST /sessions                topic + upload_ids -> run to GATE 1 -> clarifying Qs
  POST /sessions/{id}/clarify   answers -> run to GATE 2 -> plan (+ note)
  POST /sessions/{id}/plan      {approve:true} -> background generation
                                {feedback:"..."} -> re-plan, returns revised plan
  GET  /sessions/{id}           poll status (+ payload for the current gate)
  GET  /sessions/{id}/result    summary + provenance (when status == done)
  GET  /sessions/{id}/deck      download the .pptx
  DELETE /sessions/{id}         release corpus + delete staged uploads

KNOWN BOUNDARIES (acceptable for the assignment; documented intentionally):
- The checkpointer is in-memory (MemorySaver): sessions live only within THIS
  process and this graph instance. A restart loses in-flight sessions, and multiple
  worker processes would not share them. Production upgrade: SqliteSaver/PostgresSaver.
- The session store is an in-process dict (same single-process caveat). Production:
  Redis/DB.
- Per-run file logging attaches to a shared root logger; with truly concurrent
  sessions, run.log lines could interleave across sessions (console slide-tags still
  disambiguate). Fine for a single-user demo; production fix = thread-id-scoped handler.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai.graph.build import build_graph
from ai.agents.context_retriever import release
from ai.rendering.slot_map import describe_layout
from ai.utils import provenance as prov
from ai.src.logger import (attach_run_log, detach_run_log, write_slide_ordered_log,
                           get_logger)

logger = get_logger("ai.backend")

app = FastAPI(title="Agentic PPT Copilot")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
GRAPH = build_graph()                                   # built ONCE; shared across requests
UPLOAD_ROOT = Path(tempfile.gettempdir()) / "ppt_copilot_uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def index():
    if _FRONTEND.exists():
        return _FRONTEND.read_text(encoding="utf-8")
    return "<h1>frontend/index.html not found</h1>"

UPLOADS: dict[str, dict] = {}                           # upload_id -> {dir, files:[paths]}


@dataclass
class Session:
    id: str
    thread_id: str
    config: dict
    status: str = "running"
    upload_ids: list[str] = field(default_factory=list)
    deck_path: str | None = None
    result: dict | None = None
    error: str | None = None
    run_log: object = None


SESSIONS: dict[str, Session] = {}


# ── request bodies ──────────────────────────────────────────────────────────────
class CreateSession(BaseModel):
    topic: str
    upload_ids: list[str] = []


class ClarifyReq(BaseModel):
    answers: dict[str, str]


class PlanReq(BaseModel):
    approve: bool = False
    feedback: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────
def _session(sid: str) -> Session:
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, f"unknown session {sid}")
    return s


def _readable_plan(plan) -> dict:
    return {
        "deck_title": plan.deck_title,
        "subtitle": getattr(plan, "subtitle", ""),
        "note": getattr(plan, "note", ""),
        "slides": [{"position": i, "title": s.title,
                    "layout": describe_layout(s.layout_id), "kind": s.kind}
                   for i, s in enumerate(plan.slides, 1)],
    }


def _build_summary(state) -> dict:
    plan = state.get("plan")
    guardrail = state.get("guardrail") or {}
    fallbacks = state.get("fallbacks") or []
    pos = {s.slide: s.title for s in plan.slides} if plan else {}
    grounded = sorted(n for n, r in guardrail.items() if r.passed)
    return {
        "deck_title": getattr(plan, "deck_title", "") if plan else "",
        "slides": [{"position": i, "title": s.title} for i, s in enumerate(plan.slides, 1)] if plan else [],
        "verified_slides": [pos[n] for n in grounded if n in pos],
        "softened": [fb.reason for fb in fallbacks],
        "sources": sorted({os.path.basename(p.replace("\\", "/")) for p in (state.get("user_files") or [])}),
    }


async def _run_to_pause(config) -> dict:
    """Resume the graph in a worker thread (it's sync) until its next interrupt/END."""
    await asyncio.to_thread(GRAPH.invoke, None, config)
    return GRAPH.get_state(config).values


# ── endpoints ───────────────────────────────────────────────────────────────────
@app.post("/uploads")
async def upload(files: list[UploadFile] = File(...)):
    uid = uuid.uuid4().hex
    d = UPLOAD_ROOT / uid
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        dest = d / Path(f.filename or "file").name
        dest.write_bytes(await f.read())
        saved.append(str(dest))
    UPLOADS[uid] = {"dir": str(d), "files": saved}
    return {"upload_id": uid, "files": [Path(p).name for p in saved]}


@app.post("/sessions")
async def create_session(req: CreateSession):
    paths: list[str] = []
    for uid in req.upload_ids:
        u = UPLOADS.get(uid)
        if u is None:
            raise HTTPException(404, f"unknown upload_id {uid}")
        paths += u["files"]

    sid, tid = uuid.uuid4().hex, uuid.uuid4().hex
    config = {"configurable": {"thread_id": tid}}
    sess = Session(id=sid, thread_id=tid, config=config, upload_ids=list(req.upload_ids))
    sess.run_log = attach_run_log(tid)
    SESSIONS[sid] = sess

    init = {"thread_id": tid, "query": req.topic, "user_files": paths, "status": "running"}
    await asyncio.to_thread(GRAPH.invoke, init, config)
    state = GRAPH.get_state(config).values

    if state.get("status") == "blocked":
        sess.status = "blocked"
        sess.error = getattr(state.get("intent"), "reason", "request rejected by intent guard")
        return {"session_id": sid, "status": "blocked", "reason": sess.error}

    sess.status = "awaiting_clarification"
    questions = [{"question": q.question, "suggestions": list(q.suggestions)}
                 for q in (state.get("clarifying_questions") or [])]
    return {"session_id": sid, "status": sess.status, "questions": questions,
            "warnings": state.get("warnings", [])}


@app.post("/sessions/{sid}/clarify")
async def clarify(sid: str, req: ClarifyReq):
    sess = _session(sid)
    if sess.status != "awaiting_clarification":
        raise HTTPException(409, f"session is '{sess.status}', not awaiting_clarification")
    GRAPH.update_state(sess.config, {"clarification_answers": req.answers})
    state = await _run_to_pause(sess.config)
    sess.status = "awaiting_approval"
    return {"session_id": sid, "status": sess.status, "plan": _readable_plan(state["plan"])}


@app.post("/sessions/{sid}/plan")
async def plan(sid: str, req: PlanReq, background: BackgroundTasks):
    sess = _session(sid)
    if sess.status != "awaiting_approval":
        raise HTTPException(409, f"session is '{sess.status}', not awaiting_approval")

    if req.approve:
        GRAPH.update_state(sess.config, {"plan_approved": True})
        sess.status = "generating"
        background.add_task(_generate, sid)
        return {"session_id": sid, "status": "generating"}

    if req.feedback:
        GRAPH.update_state(sess.config, {"plan_approved": False, "plan_feedback": req.feedback})
        state = await _run_to_pause(sess.config)        # re-plan, pause at gate 2 again
        return {"session_id": sid, "status": sess.status, "plan": _readable_plan(state["plan"])}

    raise HTTPException(400, "provide either {approve:true} or {feedback:'...'}")


async def _generate(sid: str):
    """Background: run the approved plan to completion, then assemble result."""
    sess = SESSIONS.get(sid)
    if sess is None:
        return
    try:
        state = await _run_to_pause(sess.config)        # curate -> write -> images -> judge -> repair -> render
        sess.deck_path = state.get("deck_path")
        record = prov.build_provenance(state)
        prov.save(record, sess.thread_id)
        sess.result = {"summary": _build_summary(state), "provenance": record.to_dict()}
        sess.status = "done"
    except Exception as e:                               # noqa: BLE001 -- surface any failure to the client
        sess.status = "error"
        sess.error = str(e)
        logger.exception("[backend] generation failed for session %s", sid)
    finally:
        write_slide_ordered_log(sess.run_log)
        detach_run_log(sess.run_log)
        sess.run_log = None


@app.get("/sessions/{sid}")
async def status(sid: str):
    sess = _session(sid)
    body = {"session_id": sid, "status": sess.status}
    if sess.status == "blocked":
        body["reason"] = sess.error
    elif sess.status == "awaiting_clarification":
        state = GRAPH.get_state(sess.config).values
        body["questions"] = [{"question": q.question, "suggestions": list(q.suggestions)}
                             for q in (state.get("clarifying_questions") or [])]
    elif sess.status == "awaiting_approval":
        state = GRAPH.get_state(sess.config).values
        body["plan"] = _readable_plan(state["plan"])
    elif sess.status == "error":
        body["error"] = sess.error
    return body


@app.get("/sessions/{sid}/result")
async def result(sid: str):
    sess = _session(sid)
    if sess.status != "done":
        raise HTTPException(409, f"session is '{sess.status}', result not ready")
    return {"session_id": sid, **(sess.result or {})}


@app.get("/sessions/{sid}/deck")
async def deck(sid: str):
    sess = _session(sid)
    if not sess.deck_path or not Path(sess.deck_path).exists():
        raise HTTPException(404, "deck not ready")
    return FileResponse(
        sess.deck_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=Path(sess.deck_path).name,
    )


@app.delete("/sessions/{sid}")
async def delete_session(sid: str):
    sess = _session(sid)
    release(sess.thread_id)                              # drop curated corpus for this run
    detach_run_log(sess.run_log)
    for uid in sess.upload_ids:                          # delete staged uploads
        u = UPLOADS.pop(uid, None)
        if u:
            shutil.rmtree(u["dir"], ignore_errors=True)
    SESSIONS.pop(sid, None)
    return {"session_id": sid, "deleted": True}