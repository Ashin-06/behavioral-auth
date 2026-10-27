"""Persistence for enrollment windows and session logs: SQLite or Postgres (db.py)."""
from __future__ import annotations

import json
import threading
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import db
from .profile import Profile


class Store:
    def __init__(self, url_or_engine: str | Engine = "sqlite://"):
        self.db = db.connect(url_or_engine) if isinstance(url_or_engine, str) else url_or_engine
        self.lock = threading.Lock()
        self._profiles: dict[str, tuple[int, Profile]] = {}  # user -> (enrollment count it was fitted on, profile)

    def enroll(self, user: str, features: dict) -> int:
        with self.db.begin() as c:
            c.execute(text('INSERT INTO enrollment ("user", created, features) VALUES (:u, :t, :f)'),
                      {"u": user, "t": time.time(), "f": json.dumps(features)})
        return self.enrollment_count(user)

    def enrollment_count(self, user: str) -> int:
        with self.db.connect() as c:
            return c.execute(text('SELECT COUNT(*) FROM enrollment WHERE "user" = :u'), {"u": user}).scalar_one()

    def profile(self, user: str) -> Profile | None:
        """Refitted whenever the user has new enrollment windows, here or on another replica."""
        n = self.enrollment_count(user)
        cached = self._profiles.get(user)
        if cached and cached[0] == n:
            return cached[1]
        with self.db.connect() as c:
            rows = [json.loads(r[0]) for r in c.execute(
                text('SELECT features FROM enrollment WHERE "user" = :u ORDER BY created DESC LIMIT 200'), {"u": user})]
        p = Profile(user, rows)
        if len(rows) >= 6:
            p.fit()
        with self.lock:
            self._profiles[user] = (n, p)
        return p

    def start_session(self, sid: str, user: str) -> None:
        with self.db.begin() as c:
            c.execute(text('INSERT INTO sessions (id, "user", started) VALUES (:id, :u, :t)'),
                      {"id": sid, "u": user, "t": time.time()})

    def log(self, sid: str, a) -> None:
        with self.db.begin() as c:
            c.execute(text("INSERT INTO windows (session_id, t, trust, match, action, reasons) "
                           "VALUES (:s, :t, :trust, :m, :a, :r)"),
                      {"s": sid, "t": time.time(), "trust": a.trust, "m": a.match, "a": a.action, "r": json.dumps(a.reasons)})
            c.execute(text("UPDATE sessions SET last_trust = :trust, last_action = :a WHERE id = :s"),
                      {"trust": a.trust, "a": a.action, "s": sid})

    def sessions(self, limit: int = 50) -> list[dict]:
        out = []
        with self.db.connect() as c:
            rows = c.execute(text('SELECT id, "user", started, last_trust, last_action FROM sessions '
                                  "ORDER BY started DESC LIMIT :n"), {"n": limit}).all()
            for sid, user, started, trust, action in rows:
                tl = [{"t": t, "trust": tr, "match": m, "action": ac, "reasons": json.loads(r)} for t, tr, m, ac, r in
                      c.execute(text("SELECT t, trust, match, action, reasons FROM windows WHERE session_id = :s ORDER BY t"),
                                {"s": sid})]
                out.append({"id": sid, "user": user, "started": started, "trust": trust, "action": action, "timeline": tl})
        return out
