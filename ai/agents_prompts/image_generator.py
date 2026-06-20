"""
ai/agents_prompts/image_generator.py -- (3) visual planner

Two modes, selected by the node based on slide kind:
  * chart_system  : DATA chart-image region -> propose a ChartSpec (matplotlib).
  * image_system  : NARRATIVE region -> propose an ImageSpec (Nano Banana).
Import: from ai.agents_prompts.image_generator import chart_system, image_system, VERSION
"""

VERSION = "v1"

chart_system_v1 = """\
You design ONE chart for a slide in a corporate presentation. Given the slide
title, topic, and the slide's written content, propose chart data that visually
supports the slide.

- chart_type: "bar" for comparisons/trends over categories or years; "pie" for
  composition/share-of-total.
- points: 2-8 data points with a short label and a numeric value, consistent
  with the slide's content. Use realistic, domain-appropriate figures; if exact
  values are uncertain, use sensible round numbers (figures may be verified later).
- title: a short chart title; series_label: the unit for bar charts (e.g. "%", "bn").
Keep labels short (a year or a 1-2 word category).
"""

image_system_v1 = """\
You plan ONE illustrative image for a narrative slide. Produce an ImageSpec:
- depict: a clear, concrete description of a real, depictive scene that supports
  the slide topic (no charts, no text, no data). Avoid real named living persons.
- style_prefix: leave as provided by the system (brand style is injected).
- aspect_ratio: choose the closest of "16:9", "4:3", "1:1" to the target region.
- safety: "blocked" if the only fitting image would depict a real living person
  or anything unsafe; then give a fallback_angle (a safe alternative framing).
"""

chart_system = chart_system_v1
image_system = image_system_v1