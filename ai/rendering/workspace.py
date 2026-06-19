# """
# ai/rendering/workspace.py -- per-run scratch isolation keyed by thread_id.

# make_run_dir(thread_id) creates runs/<id>/{unpacked,gen,media_fitted} and copies
# the template into unpacked/ so assets/ is never mutated. cleanup(thread_id) sweeps
# scratch, optionally keeping deck.pptx. Prevents cross-run media collisions.
# """
# # from pathlib import Path
# # import shutil


# def make_run_dir(thread_id: str):
#     raise NotImplementedError  # TODO


# def cleanup(thread_id: str, keep_output: bool = True) -> None:
#     raise NotImplementedError  # TODO

"""
ai/rendering/workspace.py
=========================
Per-run scratch isolation keyed by thread_id.

The renderer mutates XML in place, so two concurrent requests editing the same
media/image6.png would corrupt each other. Each run gets its own copy of the
template, unpacked under runs/<thread_id>/unpacked/. assets/ is never touched.

    runs/<thread_id>/
      unpacked/      fresh OOXML tree (mutated in place)
      gen/           generated images (Nano Banana / matplotlib), pre-fit
      media_fitted/  bbox-resized images staged before injection
      deck.pptx      this run's repacked output
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from ai.rendering.pptx_io import unpack


@dataclass(frozen=True)
class RunPaths:
    root: Path
    unpacked: Path
    gen: Path
    media_fitted: Path
    deck: Path
    media: Path  # convenience: unpacked/ppt/media


def make_run_dir(thread_id: str, template_path: str | Path,
                 runs_root: str | Path = "runs") -> RunPaths:
    """Create runs/<thread_id>/ scaffolding and unpack the template into it."""
    root = Path(runs_root) / thread_id
    unpacked = root / "unpacked"
    gen = root / "gen"
    media_fitted = root / "media_fitted"
    deck = root / "deck.pptx"

    for d in (gen, media_fitted):
        d.mkdir(parents=True, exist_ok=True)
    unpack(template_path, unpacked)  # fresh copy — assets/ untouched

    return RunPaths(root=root, unpacked=unpacked, gen=gen,
                    media_fitted=media_fitted, deck=deck,
                    media=unpacked / "ppt" / "media")


def cleanup(thread_id: str, runs_root: str | Path = "runs",
            keep_output: bool = True) -> None:
    """Sweep scratch. With keep_output, preserve deck.pptx and drop the rest."""
    root = Path(runs_root) / thread_id
    if not root.exists():
        return
    if keep_output and (root / "deck.pptx").exists():
        for child in root.iterdir():
            if child.name == "deck.pptx":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    else:
        shutil.rmtree(root)