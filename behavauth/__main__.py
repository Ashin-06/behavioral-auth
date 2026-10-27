"""Command line.

    python -m behavauth evaluate          # benchmark on simulated users -> results/
    python -m behavauth realdata --cmu DSL-StrongPasswordData.csv --balabit Mouse-Dynamics-Challenge/
    python -m behavauth seed              # fill the analyst view with simulated sessions
    python -m behavauth serve             # API + demo pages (settings: BEHAVAUTH_* env)
    python -m behavauth migrate           # apply database migrations and exit
"""
from __future__ import annotations

import argparse
import json
import os
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
    r = sub.add_parser("realdata", help="score the identity model on public real-world datasets")
    r.add_argument("--cmu", help="CMU keystroke benchmark CSV (DSL-StrongPasswordData.csv)")
    r.add_argument("--balabit", help="Balabit Mouse Dynamics Challenge checkout")
    r.add_argument("--out", default="results/real_data.json")
    sub.add_parser("seed")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, help="default BEHAVAUTH_PORT or 8007")
    s.add_argument("--host", help="default BEHAVAUTH_HOST or 127.0.0.1; any other address needs API keys")
    sub.add_parser("migrate", help="apply database migrations to BEHAVAUTH_DATABASE_URL")
    a = ap.parse_args(argv)
    if a.cmd == "evaluate":
        from .evaluate import run

        print(json.dumps(run(a.users, out=a.out), indent=2))
    elif a.cmd == "realdata":
        from pathlib import Path

        from .realdata import balabit_mouse, cmu_keystroke

        res = {}
        if a.cmu:
            res["keystroke"] = cmu_keystroke(a.cmu)
        if a.balabit:
            res["mouse"] = balabit_mouse(a.balabit)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(json.dumps(res, indent=2))
    elif a.cmd == "seed":
        from . import ops

        if ops.load_settings().production:
            sys.exit("seed writes simulated users; refusing in production")
        seed()
    elif a.cmd == "migrate":
        from . import db, ops

        applied = db.migrate(db.engine(ops.load_settings().database_url))
        print(*(applied or ["up to date"]), sep=chr(10))
    else:
        import uvicorn

        from . import ops

        for name, val in (("HOST", a.host), ("PORT", a.port)):
            if val is not None:
                os.environ[f"BEHAVAUTH_{name}"] = str(val)
        try:
            settings = ops.load_settings()  # fail here, before uvicorn, with a readable message
        except ops.ConfigError as e:
            sys.exit(f"configuration error: {e}")
        ops.setup_logging(settings.log_level)
        uvicorn.run("behavauth.api:app", host=settings.host, port=settings.port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
