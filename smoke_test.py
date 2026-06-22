"""

Walks the whole gate flow over HTTP against a running server:
  uploads -> session (gate 1) -> clarify (gate 2) -> approve -> poll -> result -> deck

Clarifying questions are answered automatically (first suggestion, else a default),
so it's hands-free. This drives the REAL graph, so it spends tokens -- run it once.

Usage (server must be running -- see steps printed by --help-run):
    python smoke_test.py "Indian Banking Sector: Growth & Outlook" \
        --files C:\\path\\npa_trends.csv C:\\path\\bank_financials.xlsx
    python smoke_test.py "Indian Banking Sector"          # no files (web-grounded path)
    python smoke_test.py "..." --feedback "add more bullet slides"   # also exercise revision
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests   # pip install requests  (or swap for httpx)

BASE = "http://127.0.0.1:8000"
DEFAULT_ANSWER = "Internal management; balanced view; next 1-2 years"


def _check(r: requests.Response, label: str) -> dict:
    if r.status_code >= 400:
        print(f"  ✗ {label}: HTTP {r.status_code} -> {r.text}")
        sys.exit(1)
    print(f"  ✓ {label}: {r.status_code}")
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--feedback", default=None, help="optional: exercise the plan-revision loop once")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default="smoke_deck.pptx")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print(f"\n[0] server reachable? {base}")
    try:
        requests.get(f"{base}/docs", timeout=5)
        print("  ✓ server up")
    except Exception as e:
        print(f"  ✗ cannot reach server ({e}). Start it: uvicorn backend.main:app")
        sys.exit(1)

    upload_ids = []
    if args.files:
        print("\n[1] POST /uploads")
        files = [("files", (Path(p).name, open(p, "rb"))) for p in args.files]
        data = _check(requests.post(f"{base}/uploads", files=files), "uploads")
        upload_ids = [data["upload_id"]]
        print(f"      staged: {data['files']}")
    else:
        print("\n[1] (no files -- web-grounded path)")

    print("\n[2] POST /sessions  (runs to gate 1)")
    data = _check(requests.post(f"{base}/sessions",
                                json={"topic": args.topic, "upload_ids": upload_ids}), "sessions")
    sid = data["session_id"]
    if data["status"] == "blocked":
        print(f"  ! intent guard blocked: {data.get('reason')}")
        sys.exit(0)
    questions = data.get("questions", [])
    print(f"      session {sid} | {len(questions)} clarifying question(s)")

    answers = {}
    for q in questions:
        ans = (q["suggestions"][0] if q.get("suggestions") else DEFAULT_ANSWER)
        answers[q["question"]] = ans
        print(f"        Q: {q['question']}\n        A: {ans}")

    print("\n[3] POST /clarify  (runs to gate 2)")
    data = _check(requests.post(f"{base}/sessions/{sid}/clarify", json={"answers": answers}), "clarify")
    _show_plan(data["plan"])

    if args.feedback:
        print(f"\n[3b] POST /plan  (feedback: {args.feedback!r})")
        data = _check(requests.post(f"{base}/sessions/{sid}/plan",
                                    json={"feedback": args.feedback}), "plan-revision")
        _show_plan(data["plan"])

    print("\n[4] POST /plan  (approve -> background generation)")
    _check(requests.post(f"{base}/sessions/{sid}/plan", json={"approve": True}), "plan-approve")

    print("\n[5] GET /sessions/{id}  (polling; generation takes a few minutes)")
    t0 = time.time()
    while True:
        st = _check(requests.get(f"{base}/sessions/{sid}"), f"poll t+{int(time.time()-t0)}s")
        status = st["status"]
        if status == "done":
            break
        if status == "error":
            print(f"  ✗ generation error: {st.get('error')}")
            sys.exit(1)
        if time.time() - t0 > 900:
            print("  ✗ timed out after 15 min")
            sys.exit(1)
        time.sleep(6)

    print("\n[6] GET /result")
    res = _check(requests.get(f"{base}/sessions/{sid}/result"), "result")
    s = res["summary"]
    print(f"      deck: {s['deck_title']} | {len(s['slides'])} slides")
    print(f"      verified slides: {s['verified_slides']}")
    print(f"      softened: {s['softened']}")
    prov = res["provenance"]
    web_claims = [(sl['title'], c) for sl in prov['slides'] for c in sl.get('claims', [])
                  if c['authority'] == 'web']
    print(f"      provenance: {len(prov['slides'])} slides, {len(web_claims)} web claim(s) with URLs")
    if web_claims:
        title, c = web_claims[0]
        print(f"        e.g. [{title}] '{c['claim'][:50]}...' -> {[x['url'] for x in c['source'] if x['url']][:2]}")

    print("\n[7] GET /deck  (download)")
    r = requests.get(f"{base}/sessions/{sid}/deck")
    if r.status_code == 200:
        Path(args.out).write_bytes(r.content)
        print(f"  ✓ deck saved: {args.out} ({len(r.content)} bytes)")
    else:
        print(f"  ✗ deck: HTTP {r.status_code}")

    print("\n[8] DELETE /sessions/{id}  (cleanup)")
    _check(requests.delete(f"{base}/sessions/{sid}"), "delete")
    print("\n✓ smoke test complete.")


def _show_plan(plan: dict) -> None:
    print(f"      plan: {plan['deck_title']} -- {len(plan['slides'])} slides")
    for sl in plan["slides"]:
        print(f"        {sl['position']}. {sl['title']} ({sl['layout']})")
    if plan.get("note"):
        print(f"      note: {plan['note']}")


if __name__ == "__main__":
    main()