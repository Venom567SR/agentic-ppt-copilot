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
    if out_pptx.exists():
        out_pptx.unlink()
    with zipfile.ZipFile(out_pptx, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(src_dir).as_posix()
                z.write(path, arcname)
    return out_pptx