"""SQLite persistence for enrollment windows and session logs."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .profile import Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS enrollment (user TEXT, created REAL, features TEXT);
CREATE INDEX IF NOT EXISTS enrollment_user ON enrollment(user);
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user TEXT, started REAL, last_trust REAL, last_action TEXT);
CREATE TABLE IF NOT EXISTS windows (session_id TEXT, t REAL, trust REAL, match REAL, action TEXT, reasons TEXT);
"""


class Store:
    def __init__(self, path: str | Path = "data/behavauth.db"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        self._profiles: dict[str, Profile] = {}

    def enroll(self, user: str, features: dict) -> int:
        with self.lock:
            self.db.execute("INSERT INTO enrollment VALUES (?,?,?)", (user, time.time(), json.dumps(features)))
            self.db.commit()
            self._profiles.pop(user, None)
        return self.enrollment_count(user)

    def enrollment_count(self, user: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM enrollment WHERE user=?", (user,)).fetchone()[0]

    def profile(self, user: str) -> Profile | None:
        if user in self._profiles:
            return self._profiles[user]
        rows = [json.loads(r[0]) for r in self.db.execute("SELECT features FROM enrollment WHERE user=? ORDER BY created DESC LIMIT 200", (user,))]
        p = Profile(user, rows)
        if len(rows) >= 6:
            p.fit()
        self._profiles[user] = p
        return p

    def start_session(self, sid: str, user: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)", (sid, user, time.time(), None, None))
            self.db.commit()

    def log(self, sid: str, a) -> None:
        with self.lock:
            self.db.execute("INSERT INTO windows VALUES (?,?,?,?,?,?)", (sid, time.time(), a.trust, a.match, a.action, json.dumps(a.reasons)))
            self.db.execute("UPDATE sessions SET last_trust=?, last_action=? WHERE id=?", (a.trust, a.action, sid))
            self.db.commit()

    def sessions(self, limit: int = 50) -> list[dict]:
        out = []
        for sid, user, started, trust, action in self.db.execute(
                "SELECT id, user, started, last_trust, last_action FROM sessions ORDER BY started DESC LIMIT ?", (limit,)):
            tl = [{"t": t, "trust": tr, "match": m, "action": ac, "reasons": json.loads(r)} for t, tr, m, ac, r in
                  self.db.execute("SELECT t, trust, match, action, reasons FROM windows WHERE session_id=? ORDER BY t", (sid,))]
            out.append({"id": sid, "user": user, "started": started, "trust": trust, "action": action, "timeline": tl})
        return out
