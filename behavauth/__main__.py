"""Command line.

    python -m behavauth evaluate          # benchmark on simulated users -> results/
    python -m behavauth seed              # fill the analyst view with simulated sessions
    python -m behavauth serve --port 8007
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

import numpy as np


def seed(db: str | None = None) -> None:
    from . import simulate as S
    from .engine import Session
    from .features import window_features
    from .store import Store

    store = Store(db) if db else __import__("behavauth.api", fromlist=["store"]).store
    rng = np.random.default_rng(42)
    owner, intruder = S.person(rng), S.person(rng)
    for _ in range(3):
        for w in S.windows(S.session("genuine", owner, rng, 60)):
            store.enroll("demo-priya", window_features(w))
    for kind in ("genuine", "impostor", "bot", "rat", "coached"):
        sid = uuid.uuid4().hex
        store.start_session(sid, "demo-priya")
        s = Session("demo-priya", store.profile("demo-priya"))
        for w in S.windows(S.session(kind, owner, rng, 75, intruder=intruder)):
            store.log(sid, s.observe(w))
        print(f"{kind:9s} final trust {s.trust:.2f}  transfer: {s.gate('transfer', 20000)['decision']}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="behavauth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--users", type=int, default=30)
    e.add_argument("--out", default="results")
    sub.add_parser("seed")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8007)
    s.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    if a.cmd == "evaluate":
        from .evaluate import run

        print(json.dumps(run(a.users, out=a.out), indent=2))
    elif a.cmd == "seed":
        seed()
    else:
        import uvicorn

        uvicorn.run("behavauth.api:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
