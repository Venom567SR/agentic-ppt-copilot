"""
==================
Project logger — UTF-8 safe (Windows consoles default to cp1252 and choke on
non-ASCII), single handler per name, readable format. Used across agents so a
run leaves a traceable trail (task, prompt_version, model, latency).
"""
from __future__ import annotations

import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:                       # already configured
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    try:                                      # force UTF-8 on Windows
        handler.stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logger.addHandler(handler)
    logger.propagate = False
    return logger