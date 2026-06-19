"""
backend/main.py -- FastAPI service (thin wrapper over ai/).

Resumable HITL contract:
    POST /generate         -> start; returns {status, thread_id, question?}
    POST /resume           -> answer a gate; re-enters the graph at its checkpoint
    GET  /result/{thread_id} -> returns the .pptx + per-slide citations
"""
# from fastapi import FastAPI
# app = FastAPI()
# TODO: wire endpoints to ai.graph.build
