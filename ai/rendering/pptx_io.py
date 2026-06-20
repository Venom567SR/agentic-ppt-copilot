"""
ai/rendering/pptx_io.py
=======================
Self-contained unpack/pack for .pptx (OOXML) using only the stdlib.
No external scripts — portable across any environment.

A .pptx is a zip with [Content_Types].xml at the root. Unpacking = extract all;
packing = re-zip the tree (entries relative to the package root, forward slashes).
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def unpack(pptx_path: str | Path, dest_dir: str | Path) -> Path:
    """Extract a .pptx into dest_dir (created fresh). Returns dest_dir."""
    pptx_path, dest_dir = Path(pptx_path), Path(dest_dir)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pptx_path, "r") as z:
        z.extractall(dest_dir)
    return dest_dir


def pack(src_dir: str | Path, out_pptx: str | Path) -> Path:
    """Zip an unpacked tree back into a .pptx. Returns out_pptx."""
    src_dir, out_pptx = Path(src_dir), Path(out_pptx)
    out_pptx.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file first, then move into place. If the target is locked
    # (e.g. the previous deck is still open in PowerPoint on Windows), fall back
    # to a timestamped name instead of crashing after a long agent run.
    tmp = out_pptx.with_suffix(out_pptx.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(src_dir).as_posix())

    try:
        tmp.replace(out_pptx)                      # atomic overwrite
        return out_pptx
    except PermissionError:
        import time
        alt = out_pptx.with_name(f"{out_pptx.stem}_{int(time.time())}{out_pptx.suffix}")
        tmp.replace(alt)
        return alt                                 # caller gets the path actually written