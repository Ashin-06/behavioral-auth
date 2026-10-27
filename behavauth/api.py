"""Behavioural authentication service.

    python -m behavauth serve            # settings: BEHAVAUTH_* environment variables

Enrollments and session logs are in the database. A live session's trust score is kept
in this process: after a restart, or on another replica, the client starts a new
session, and sensitive actions step up until enough behaviour has been seen again.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ops
from .engine import Session
from .features import window_features
from .profile import MIN_WINDOWS
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
settings = ops.load_settings()
ops.setup_logging(settings.log_level)
store = Store(settings.database_url)
live: dict[str, Session] = {}
last_seen: dict[str, float] = {}
SESSION_IDLE_S = float(os.environ.get("BEHAVAUTH_SESSION_IDLE_S", 2 * 3600))
require_key = ops.require("score")


def _prune(now: float) -> None:
    """Drop sessions idle for longer than SESSION_IDLE_S so memory stays bounded."""
    for sid in [s for s, t in last_seen.items() if now - t > SESSION_IDLE_S]:
        live.pop(sid, None)
        last_seen.pop(sid, None)


_lock = threading.Lock()
app = FastAPI(title="Behavioural Auth", version="1.0.0")
ops.install(app, settings, {"database": lambda: store.db.connect().close()})
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


class Event(BaseModel):
    t: float
    type: Literal["kd", "ku", "mm", "md", "mu", "paste", "focus", "blur", "vis"]
    k: str | None = None
    f: str | None = Field(default=None, max_length=40)
    i: int | None = None
    x: float | None = None
    y: float | None = None
    v: str | None = None


class Batch(BaseModel):
    events: list[Event] = Field(..., max_length=20_000)


class EnrollIn(Batch):
    user: str = Field(..., min_length=1, max_length=64)


class SessionIn(BaseModel):
    user: str = Field(..., min_length=1, max_length=64)


class ActionIn(BaseModel):
    kind: Literal["transfer", "add_payee", "change_phone", "view"]
    amount: float = Field(0.0, ge=0, allow_inf_nan=False)


def _events(b: Batch) -> list[dict]:
    return sorted((e.model_dump(exclude_none=True) for e in b.events), key=lambda e: e["t"])


@app.get("/")
def bank():
    return FileResponse(ROOT / "web" / "bank.html")


@app.get("/analyst")
def analyst():
    return FileResponse(ROOT / "web" / "analyst.html")


@app.get("/api/users/{user}", dependencies=[Depends(require_key)])
def user_status(user: str):
    n = store.enrollment_count(user)
    return {"user": user, "windows": n, "needed": MIN_WINDOWS, "ready": n >= MIN_WINDOWS}


@app.post("/api/enroll", dependencies=[Depends(require_key)])
def enroll(body: EnrollIn):
    ev = _events(body)
    f = window_features(ev)
    usable = sum(1 for k in ("dwell_mean", "speed_mean") if f[k] == f[k])  # not NaN
    if usable == 0:
        raise HTTPException(422, "not enough typing or mouse movement in this batch")
    n = store.enroll(body.user, f)
    return {"windows": n, "needed": MIN_WINDOWS, "ready": n >= MIN_WINDOWS}


@app.post("/api/session", dependencies=[Depends(require_key)])
def start(body: SessionIn):
    sid = uuid.uuid4().hex
    p = store.profile(body.user)
    with _lock:
        now = time.time()
        _prune(now)
        live[sid] = Session(body.user, p)
        last_seen[sid] = now
    store.start_session(sid, body.user)
    return {"session_id": sid, "profile_ready": bool(p and p.ready)}


def _get(sid: str) -> Session:
    s = live.get(sid)
    if s is None:
        raise HTTPException(404, "unknown or expired session")
    last_seen[sid] = time.time()
    return s


@app.post("/api/session/{sid}/events", dependencies=[Depends(require_key)])
def observe(sid: str, body: Batch):
    s = _get(sid)
    with _lock:
        a = s.observe(_events(body))
    store.log(sid, a)
    ops.DECISIONS.labels(decision=f"window_{a.action}").inc()
    return asdict(a)


@app.post("/api/session/{sid}/action", dependencies=[Depends(require_key)])
def action(sid: str, body: ActionIn):
    out = _get(sid).gate(body.kind, body.amount)
    ops.DECISIONS.labels(decision=f"action_{out['decision']}").inc()
    return out


@app.get("/api/sessions", dependencies=[Depends(ops.require("review"))])
def sessions(limit: int = Query(50, ge=1)):
    return store.sessions(min(limit, 200))
