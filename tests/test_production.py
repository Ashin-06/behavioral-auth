"""Settings, auth, limits, headers, metrics, health, persistence and migrations."""
import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from behavauth import db, ops
from behavauth import simulate as S
from behavauth.features import window_features
from behavauth.store import Store

KEY = "behavauth_" + "x" * 40
HASHED = {f"sha256:{hashlib.sha256(KEY.encode()).hexdigest()}": {"user": "netbanking", "role": "bank_backend"}}


def prod_env(**over):
    env = {"BEHAVAUTH_ENV": "production", "BEHAVAUTH_API_KEYS": json.dumps(HASHED), "BEHAVAUTH_DATABASE_URL": "sqlite://"}
    env.update(over)
    return {k: v for k, v in env.items() if v is not None}


def boot(monkeypatch, **env):
    for k in [k for k in os.environ if k.startswith("BEHAVAUTH_")]:
        monkeypatch.delenv(k)
    env.setdefault("DATABASE_URL", "sqlite://")
    for k, v in env.items():
        monkeypatch.setenv(f"BEHAVAUTH_{k}", v)
    import behavauth.api as api

    return importlib.reload(api)


def test_production_settings_accepted():
    s = ops.load_settings(prod_env())
    assert s.production and not s.demo and s.database_url == "sqlite://"


@pytest.mark.parametrize("change, message", [
    ({"BEHAVAUTH_API_KEYS": None}, "API keys"),
    ({"BEHAVAUTH_DATABASE_URL": None}, "DATABASE_URL"),
    ({"BEHAVAUTH_API_KEYS": json.dumps({KEY: {"user": "netbanking", "role": "bank_backend"}})}, "sha256"),
    ({"BEHAVAUTH_API_KEYS": json.dumps({"sha256:" + "0" * 64: {"user": "x", "role": "root"}})}, "roles"),
    ({"BEHAVAUTH_CORS_ORIGINS": "*"}, "CORS"),
    ({"BEHAVAUTH_ENV": "prod"}, "development or production"),
    ({"BEHAVAUTH_DATABASE_URL": "mysql://x"}, "postgresql"),
])
def test_production_refuses_to_start(change, message):
    with pytest.raises(ops.ConfigError, match=message):
        ops.load_settings(prod_env(**change))


def test_database_settings():
    assert ops.load_settings(prod_env(BEHAVAUTH_DATABASE_URL=None, BEHAVAUTH_DB="/data/b.db")).database_url == "sqlite:////data/b.db"
    dev = ops.load_settings({})
    assert dev.demo and dev.database_url.startswith("sqlite:///") and dev.database_url.endswith("data/behavauth.db")


def test_no_public_bind_without_keys():
    with pytest.raises(ops.ConfigError, match="without API keys"):
        ops.load_settings({"BEHAVAUTH_HOST": "0.0.0.0"})
    assert ops.load_settings({"BEHAVAUTH_HOST": "0.0.0.0", "BEHAVAUTH_API_KEYS": json.dumps(HASHED)}).host == "0.0.0.0"


def test_serve_exits_with_a_readable_error():
    env = {k: v for k, v in os.environ.items() if not k.startswith("BEHAVAUTH_")}
    r = subprocess.run([sys.executable, "-m", "behavauth", "serve", "--host", "0.0.0.0"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "without API keys" in r.stderr


def test_seed_refused_in_production():
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("BEHAVAUTH_")},
           **prod_env()}
    r = subprocess.run([sys.executable, "-m", "behavauth", "seed"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "refusing in production" in r.stderr


def test_roles_decide_what_a_key_may_do(monkeypatch):
    keys = {"k-bank": {"user": "netbanking", "role": "bank_backend"}, "k-an": {"user": "asha", "role": "analyst"},
            "k-mon": {"user": "prom", "role": "monitor"}}
    c = TestClient(boot(monkeypatch, API_KEYS=json.dumps(keys)).app)
    assert c.post("/api/session", json={"user": "priya"}).status_code == 401
    assert c.post("/api/session", json={"user": "priya"}, headers={"x-api-key": "wrong"}).status_code == 401
    sid = c.post("/api/session", json={"user": "priya"}, headers={"x-api-key": "k-bank"}).json()["session_id"]
    assert c.post(f"/api/session/{sid}/action", json={"kind": "view"}, headers={"authorization": "Bearer k-an"}).status_code == 403
    assert c.get("/api/sessions", headers={"x-api-key": "k-bank"}).status_code == 403
    assert c.get("/api/sessions", headers={"x-api-key": "k-an"}).json()[0]["id"] == sid
    assert c.post(f"/api/session/{sid}/action", json={"kind": "transfer", "amount": 5000},
                  headers={"x-api-key": "k-bank"}).json()["decision"] == "step_up"
    assert c.get("/metrics", headers={"x-api-key": "k-bank"}).status_code == 403
    m = c.get("/metrics", headers={"x-api-key": "k-mon"})
    assert m.status_code == 200 and 'http_requests_total{method="POST",route="/api/session",status="200"}' in m.text
    assert 'behavauth_decisions_total{decision="action_step_up"}' in m.text
    assert c.get("/").status_code == 200 and c.get("/static/capture.js").status_code == 200  # the demo pages are static


def test_rate_limit(monkeypatch):
    c = TestClient(boot(monkeypatch, RATE_LIMIT="3").app)
    codes = [c.get("/api/users/priya").status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
    assert int(c.get("/api/users/priya").headers["retry-after"]) >= 1
    assert c.get("/healthz").status_code == 200  # probes are never limited


def test_body_size_cap(monkeypatch):
    c = TestClient(boot(monkeypatch, MAX_BODY_BYTES="1000").app)
    assert c.post("/api/enroll", json={"user": "u", "events": [{"t": i, "type": "mm", "x": 1, "y": 2} for i in range(100)]}).status_code == 413

    def chunks():  # no content-length: the cap still holds
        for _ in range(20):
            yield b"a" * 100

    assert c.post("/api/enroll", content=chunks(), headers={"content-type": "application/json"}).status_code == 413
    assert c.post("/api/session", json={"user": "u"}).status_code == 200


def test_headers_and_request_ids(monkeypatch):
    c = TestClient(boot(monkeypatch).app)
    r = c.get("/api/users/priya", headers={"x-request-id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == ops.API_CSP and r.headers["cache-control"] == "no-store"
    assert "unsafe-inline" in c.get("/").headers["content-security-policy"]
    assert len(c.get("/healthz", headers={"x-request-id": "bad id\n"}).headers["x-request-id"]) == 32
    assert "access-control-allow-origin" not in c.get("/healthz", headers={"origin": "https://evil.example"}).headers


def test_cors_only_for_listed_origins(monkeypatch):
    c = TestClient(boot(monkeypatch, CORS_ORIGINS="https://netbanking.bank.example").app)
    ok = c.get("/healthz", headers={"origin": "https://netbanking.bank.example"})
    assert ok.headers["access-control-allow-origin"] == "https://netbanking.bank.example"
    assert "access-control-allow-origin" not in c.get("/healthz", headers={"origin": "https://evil.example"}).headers


def test_errors_do_not_leak(monkeypatch):
    api = boot(monkeypatch)

    @api.app.get("/boom")
    def boom():
        raise RuntimeError("secret detail: customer priya.sharma")

    c = TestClient(api.app)
    r = c.get("/boom")
    assert r.status_code == 500 and "priya" not in r.text and r.json()["request_id"] == r.headers["x-request-id"]
    bad = c.post("/api/session", json={"user": ["priya.sharma"]})
    assert bad.status_code == 422 and "priya" not in bad.text
    sid = c.post("/api/session", json={"user": "u"}).json()["session_id"]
    assert c.post(f"/api/session/{sid}/action", content=b'{"kind": "transfer", "amount": NaN}',
                  headers={"content-type": "application/json"}).status_code == 422


def test_health_and_readiness(monkeypatch):
    api = boot(monkeypatch)
    c = TestClient(api.app)
    assert c.get("/healthz").json() == {"status": "ok"}
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {"database": True}
    api.store.db.dispose()
    monkeypatch.setattr(api.store.db, "connect", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    r = c.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["database"] is False and "db down" not in r.text


def test_json_logs_carry_request_ids(capsys):
    ops.setup_logging("INFO")
    token = ops.request_id.set("rid-1")
    ops.log.info("hello", extra={"fields": {"n": 1}})
    ops.request_id.reset(token)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["msg"] == "hello" and line["request_id"] == "rid-1" and line["n"] == 1 and line["level"] == "INFO"


def _url(tmp_path):
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'state.db'}"


def test_enrollment_and_sessions_survive_a_restart(tmp_path):
    url, user = _url(tmp_path), f"restart-{os.getpid()}-{tmp_path.name}"
    rng = np.random.default_rng(3)
    a = Store(url)
    for w in S.windows(S.session("genuine", S.person(rng), rng, 120)):
        a.enroll(user, window_features(w))
    a.start_session("sid-" + user, user)
    replica = Store(url)  # a new process or replica, same database
    assert replica.enrollment_count(user) == a.enrollment_count(user) >= 6
    assert replica.profile(user).ready
    assert "sid-" + user in {s["id"] for s in replica.sessions(200)}

    p = a.profile(user)
    replica.enroll(user, window_features(S.windows(S.session("genuine", S.person(rng), rng, 20))[0]))
    assert a.profile(user) is not p  # the other replica's enrollment refits this one's cached profile


def test_a_database_from_before_migrations_upgrades_in_place(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)  # the schema the 0.x store created by hand
    old.executescript("""
        CREATE TABLE IF NOT EXISTS enrollment (user TEXT, created REAL, features TEXT);
        CREATE INDEX IF NOT EXISTS enrollment_user ON enrollment(user);
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user TEXT, started REAL, last_trust REAL, last_action TEXT);
        CREATE TABLE IF NOT EXISTS windows (session_id TEXT, t REAL, trust REAL, match REAL, action TEXT, reasons TEXT);
        INSERT INTO enrollment VALUES ('asha', 1.0, '{}');
    """)
    old.close()
    s = Store(f"sqlite:///{path}")
    assert s.enrollment_count("asha") == 1


def test_migrations_apply_once(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    eng = db.engine(url)
    assert db.migrate(eng) == ["001_init.sql"]
    assert db.migrate(eng) == []
    with eng.connect() as c:
        assert [r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))] == [1]
        tables = {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert {"enrollment", "sessions", "windows"} <= tables
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("BEHAVAUTH_")}, "BEHAVAUTH_DATABASE_URL": url}
    out = subprocess.run([sys.executable, "-m", "behavauth", "migrate"], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "up to date" in out.stdout
