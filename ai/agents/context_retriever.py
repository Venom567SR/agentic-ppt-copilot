"""
ai/agents/context_retriever.py -- user-file grounding: curator agent + extraction tool

Design (your model): the TOOL extracts + chunks files (domain-blind); the AGENT
(LLM) reads the chunks in batches against the PRESENTATION AGENDA and keeps only
the relevant ones as temporary, in-memory context. No BM25, no ranking, no
hardcoded vocabulary -- relevance is the model's judgment, so it works in any
domain. Kept chunks are used VERBATIM (exact figures preserved for the judge).

  build_corpus(paths)            -> Corpus           (extract + dedup + enforce cap)
  corpus.map_for_planner()       -> compact map for clarifier / manager
  curate(corpus, agenda)         -> CuratedMemory    (LLM-selected, verbatim, in-RAM)
  memory.as_evidence() / sources / discard()

Bounded by design: at most MAX_FILES files and ~MAX_TOKENS of extracted text per
presentation (rejected otherwise), so the curator never overruns context. The
CuratedMemory is in-RAM only and discarded after the deck is generated -- nothing
is persisted; nothing crosses sessions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ai.agents.base import BaseAgent
from ai.agents_prompts.context_retriever import system_prompt as SYSTEM_PROMPT, VERSION
from ai.tools.doc_extract import extract_all, approx_tokens, Chunk
from ai.schemas import CuratedSelection, Source
from ai.src.logger import get_logger

logger = get_logger(__name__)

# Product/safety limits per presentation (not domain logic): keep the demo bounded
# and the curator's input within the context window.
MAX_FILES = 3
MAX_TOKENS = 45_000
# Per-batch budget for the curator call (well under the model's input limit).
_BATCH_TOKENS = 30_000


# ── corpus (extraction tool side) ───────────────────────────────────────────────
@dataclass
class Corpus:
    chunks: list[Chunk]
    headings_by_source: dict[str, list[str]]

    def map_for_planner(self, max_chars: int = 1500) -> str:
        """Compact map for the clarifier/manager: what's available, never content."""
        if not self.chunks:
            return ""
        lines = []
        for src, heads in self.headings_by_source.items():
            n = sum(1 for c in self.chunks if c.source == src)
            tables = sum(1 for c in self.chunks if c.source == src and c.is_table)
            head = ("; ".join(heads[:4]) if heads else "(no headings)")
            lines.append(f"- {src}: {n} sections ({tables} tables). Topics: {head}")
        return ("User-provided documents (ground truth):\n" + "\n".join(lines))[:max_chars]


def build_corpus(paths: list[str]) -> Corpus:
    """Extract all files into a session-scoped Corpus. Dedups identical boilerplate
    prose across files and enforces the per-presentation cap. Over the file cap, it
    uses the FIRST MAX_FILES (so uploads are still grounded) rather than discarding
    them; the token cap still raises (content genuinely too large)."""
    if len(paths) > MAX_FILES:
        logger.warning("[context_retriever] %d files uploaded; using the first %d (per-deck cap).",
                       len(paths), MAX_FILES)
        paths = paths[:MAX_FILES]

    docs = extract_all(paths)
    chunks: list[Chunk] = []
    headings: dict[str, list[str]] = {}
    seen: set[str] = set()
    dropped = 0
    for d in docs:
        headings[d.source] = d.headings
        for c in d.chunks:
            key = c.text.strip().lower()
            if not c.is_table and key in seen:     # dedup prose only; tables are distinct
                dropped += 1
                continue
            seen.add(key)
            chunks.append(c)

    total = sum(approx_tokens(c.text) for c in chunks)
    if total > MAX_TOKENS:
        raise ValueError(f"Uploaded content too large: ~{total} tokens "
                         f"(limit {MAX_TOKENS}). Use fewer/smaller files.")
    logger.info("[context_retriever] corpus: %d chunks from %d file(s), ~%d tokens%s",
                len(chunks), len(docs), total,
                f" ({dropped} duplicate prose chunks collapsed)" if dropped else "")
    return Corpus(chunks=chunks, headings_by_source=headings)


# ── curated memory (temporary, in-RAM) ──────────────────────────────────────────
@dataclass
class CuratedMemory:
    """Verbatim chunks the agent judged relevant to the deck agenda. In-RAM only;
    call discard() after generation. Shared across slides (deck_writer / judge)."""
    chunks: list[Chunk] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.chunks)

    def as_evidence(self, char_cap: int | None = None) -> str:
        blocks, used = [], 0
        for c in self.chunks:
            block = f"[{c.source} | {c.location}]\n{c.text}"
            if char_cap and used + len(block) > char_cap and blocks:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)

    def sources(self) -> list[Source]:
        now = datetime.now(timezone.utc)
        out, seen = [], set()
        for c in self.chunks:
            if c.source not in seen:
                seen.add(c.source)
                out.append(Source(url=c.source, title=c.source,
                                  retrieved_at=now, authority="user_file"))
        return out

    def discard(self) -> None:
        """Explicit teardown: drop the curated context after the deck is built."""
        self.chunks = []


# ── curator (BaseAgent) ─────────────────────────────────────────────────────────
class ContextCurator(BaseAgent[CuratedSelection]):
    task = "context_curator"
    system_prompt = SYSTEM_PROMPT
    prompt_version = VERSION
    output_schema = CuratedSelection
    temperature = 0.0          # selection should be stable, not creative

    def build_user_message(self, state) -> str:
        return (f"PRESENTATION AGENDA:\n{state['_cur_agenda']}\n\n"
                f"DOCUMENT CHUNKS (keep the relevant IDs):\n{state['_cur_render']}\n\n"
                f"Return the IDs to keep (empty list if none are relevant).")


_agent = ContextCurator()


def _render_batch(items: list[tuple[int, Chunk]]) -> str:
    out = []
    for cid, c in items:
        kind = "TABLE" if c.is_table else "text"
        out.append(f"[ID {cid}] ({c.source} | {c.location} | {kind})\n{c.text}")
    return "\n\n".join(out)


def _batches(chunks: list[Chunk]) -> list[list[tuple[int, Chunk]]]:
    """Split (global_id, chunk) pairs into batches under the per-call token budget."""
    batches, cur, budget = [], [], 0
    for i, c in enumerate(chunks):
        t = approx_tokens(c.text)
        if cur and budget + t > _BATCH_TOKENS:
            batches.append(cur)
            cur, budget = [], 0
        cur.append((i, c))
        budget += t
    if cur:
        batches.append(cur)
    return batches


def curate(corpus: Corpus, agenda: str) -> CuratedMemory:
    """Read chunks in batches (LLM) and keep only those relevant to the agenda.
    A batch whose LLM call fails contributes nothing (a gap), with no keyword
    fallback -- empty memory signals 'no user evidence' to the supervisor."""
    if not corpus.chunks:
        return CuratedMemory([])
    kept: set[int] = set()
    for batch in _batches(corpus.chunks):
        valid = {cid for cid, _ in batch}
        try:
            sel = _agent.run({"_cur_agenda": agenda, "_cur_render": _render_batch(batch)})
            kept.update(i for i in sel.keep_ids if i in valid)
        except Exception as e:
            logger.warning("[context_retriever] curation batch failed (%s); skipping batch", e)
    chosen = [corpus.chunks[i] for i in sorted(kept)]
    logger.info("[context_retriever] curated %d/%d chunks for the agenda",
                len(chosen), len(corpus.chunks))
    return CuratedMemory(chosen)


# ── graph node adapters ─────────────────────────────────────────────────────────
# Session-scoped corpus cache keyed by thread_id. The heavy Corpus (chunks) lives
# here, NOT in GraphState, so the checkpointer only ever serializes small strings.
# release(thread_id) drops it after the deck is generated (temporary, per session).
_SESSION: dict[str, "Corpus"] = {}


def ingest_node(state) -> dict:
    """Build the corpus from uploaded files (before clarify) -> corpus_map.
    Over the file cap, use the first MAX_FILES and warn (run stays file-grounded);
    only a genuine token-size overflow degrades to no corpus."""
    paths = state.get("user_files") or []
    if not paths:
        return {}
    warnings = []
    if len(paths) > MAX_FILES:
        warnings.append(f"Used the first {MAX_FILES} of {len(paths)} uploaded files "
                        f"(per-deck limit); the rest were not used for grounding.")
    try:
        corpus = build_corpus(paths)
    except ValueError as e:                       # token cap exceeded -> proceed without files
        logger.warning("[context_retriever] %s", e)
        return {"warnings": [str(e)]}
    _SESSION[state["thread_id"]] = corpus
    out = {"corpus_map": corpus.map_for_planner()}
    if warnings:
        out["warnings"] = warnings
    return out


def _agenda_from_plan(plan) -> str:
    titles = "\n".join(f"- {s.title} [{s.kind}]" for s in plan.slides)
    return f"{plan.deck_title}\nSlides:\n{titles}"


def curate_node(state) -> dict:
    """Curate user-file evidence against the approved plan (the agenda) -> the
    temporary, in-RAM curated_evidence used by deck_writer/judge."""
    corpus = _SESSION.get(state.get("thread_id"))
    if corpus is None:
        return {}
    mem = curate(corpus, _agenda_from_plan(state["plan"]))
    return {"curated_evidence": mem.as_evidence(), "sources": mem.sources()}


def release(thread_id: str) -> None:
    """Drop this session's corpus after generation (explicit teardown)."""
    _SESSION.pop(thread_id, None)