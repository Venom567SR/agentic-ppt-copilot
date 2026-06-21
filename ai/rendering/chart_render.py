"""
ai/rendering/chart_render.py
============================
Deterministic brand-palette charts (matplotlib) for DATA chart-image regions.
Renders to a PNG sized to the target media box so swap_image drops it in cleanly.
No LLM here -- it consumes a ChartSpec the visual planner produced.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ICICI Prudential AMC palette (primary + secondary), in a sensible cycle order.
BRAND = ["#DB620A", "#053C6D", "#97291E", "#FDB92A", "#917BB9", "#00C0F3",
         "#F4858E", "#D1CFBB"]
NAVY = "#053C6D"


def _figure(width_px: int, height_px: int, dpi: int = 150):
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    fig.patch.set_facecolor("white")
    return fig


def render_chart(spec, width_px: int, height_px: int, out_path: str | Path) -> Path:
    """Render a ChartSpec (bar|pie) to a brand-styled PNG of the given pixel size."""
    out_path = Path(out_path)
    labels = [p.label for p in spec.points]
    values = [p.value for p in spec.points]
    colors = [BRAND[i % len(BRAND)] for i in range(len(values))]

    fig = _figure(width_px, height_px)
    ax = fig.add_subplot(111)

    if spec.chart_type == "pie":
        ax.pie(values, labels=labels, colors=colors, autopct="%1.0f%%",
               textprops={"color": NAVY, "fontsize": 9}, startangle=90)
        ax.axis("equal")
    else:  # bar
        ax.bar(labels, values, color=colors)
        ax.set_ylabel(spec.series_label or "", color=NAVY, fontsize=9)
        ax.tick_params(colors=NAVY, labelsize=9)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#CCCCCC")

    if spec.title:
        ax.set_title(spec.title, color=NAVY, fontsize=11, fontweight="bold")

    # Pad internally and save at EXACTLY width_px x height_px (no tight crop, which
    # would change the aspect and oversize the image inside its slide frame).
    fig.subplots_adjust(left=0.08, right=0.92, top=0.86, bottom=0.12)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path