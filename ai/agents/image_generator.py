"""
ai/agents/image_generator.py -- (3) visual planner + generator (Gemini 2.5 Pro)

For each slide that has an image region:
  * DATA  -> plan a ChartSpec, render a brand chart (matplotlib), swap in.
  * NARRATIVE -> plan an ImageSpec, generate via Nano Banana, swap in.
Sets SlideContent.image to the generated PNG path; render_deck swaps it into the
region (resizing to the exact media box).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from ai.agents.base import BaseAgent
from ai.agents_prompts.image_generator import chart_system, image_system, VERSION
from ai.schemas import ChartSpec, ImageSpec, SlideContent
from ai.graph.state import GraphState
from ai.rendering.slot_map import by_id
from ai.rendering.chart_render import render_chart
from ai.src.logger import get_logger

logger = get_logger(__name__)

BRAND_STYLE = ("clean professional editorial illustration, ICICI orange (#DB620A) "
               "and navy (#053C6D) palette, financial-report aesthetic, flat vector "
               "style, no text, no charts")


def _slide_text_blob(sc: SlideContent) -> str:
    return " | ".join(" ".join(v.lines) for v in sc.text.values())


class ChartPlanner(BaseAgent[ChartSpec]):
    task = "image_generator"
    system_prompt = chart_system
    prompt_version = VERSION
    output_schema = ChartSpec
    temperature = 0.3

    def build_user_message(self, state: GraphState) -> str:
        sc: SlideContent = state["_for"]
        return (f"Topic: {state['query']}\nSlide title: {state.get('_title','')}\n"
                f"Slide content: {_slide_text_blob(sc)}\n\nDesign the chart.")


class ImagePlanner(BaseAgent[ImageSpec]):
    task = "image_generator"
    system_prompt = image_system
    prompt_version = VERSION
    output_schema = ImageSpec
    temperature = 0.5

    def build_user_message(self, state: GraphState) -> str:
        sc: SlideContent = state["_for"]
        return (f"Topic: {state['query']}\nSlide title: {state.get('_title','')}\n"
                f"Slide content: {_slide_text_blob(sc)}\n\nPlan the illustration.")


_chart = ChartPlanner()
_image = ImagePlanner()


def node(state: GraphState) -> dict:
    slides: list[SlideContent] = state["slides"]
    plan = state["plan"]
    kind_by_slide = {p.slide: p.kind for p in plan.slides}
    title_by_slide = {p.slide: p.title for p in plan.slides}
    gen_dir = Path(state.get("_gen_dir") or tempfile.mkdtemp(prefix="ppt_gen_"))

    for sc in slides:
        layout = by_id(sc.layout_id)
        if not layout.image:
            continue
        kind = kind_by_slide.get(sc.slide, "data")
        ctx = {**state, "_for": sc, "_title": title_by_slide.get(sc.slide, "")}
        try:
            if kind == "data":
                spec = _chart.run(ctx)
                png = render_chart(spec, layout.image.w, layout.image.h,
                                   gen_dir / f"chart_{sc.slide}.png")
                sc.image = str(png)
                logger.info("[image_generator] slide %s -> %s chart", sc.slide, spec.chart_type)
            else:
                spec = _image.run(ctx)
                if spec.safety == "blocked":
                    logger.warning("[image_generator] slide %s image blocked: %s",
                                   sc.slide, spec.fallback_angle)
                    continue
                from ai.tools.gemini_image import generate_image
                prompt = f"{spec.depict}. {BRAND_STYLE}."
                png = generate_image(prompt, gen_dir / f"img_{sc.slide}.png")
                sc.image = str(png)
                logger.info("[image_generator] slide %s -> generated illustration", sc.slide)
        except Exception as e:
            logger.warning("[image_generator] slide %s visual failed (%s); leaving region as-is",
                           sc.slide, e)

    return {"slides": slides}