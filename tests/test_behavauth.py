import numpy as np
import pytest
from fastapi.testclient import TestClient

from behavauth import simulate as S
from behavauth.engine import Session
from behavauth.features import keystroke_features, mouse_features, window_features
from behavauth.profile import Profile
from behavauth.threats import bot_signals, coaching_signals, remote_signals


@pytest.fixture(scope="module")
def world():
    rng = np.random.default_rng(3)
    people = [S.person(rng) for _ in range(6)]
    profiles = [Profile("u", [window_features(w) for _ in range(3) for w in S.windows(S.session("genuine", p, rng, 60))]).fit()
                for p in people]
    return rng, people, profiles


def test_keystroke_timing_extraction():
    ev = []
    for i in range(10):
        ev += [{"t": i * 200.0, "type": "kd", "k": "letter", "f": "a", "i": i}, {"t": i * 200.0 + 80, "type": "ku", "k": "letter", "f": "a", "i": i}]
    f = keystroke_features(ev)
    assert f["dwell_mean"] == pytest.approx(80) and f["dd_mean"] == pytest.approx(200) and f["flight_mean"] == pytest.approx(120)


def test_mouse_straight_line_is_straight():
    ev = [{"t": i * 8.0, "type": "mm", "x": i * 5.0, "y": 100.0} for i in range(60)]
    f = mouse_features(ev)
    assert f["straightness"] > 0.99 and f["sample_ms_median"] == pytest.approx(8)


def test_genuine_matches_better_than_impostor(world):
    rng, people, profiles = world
    gen = [profiles[0].match(window_features(w))[0] for w in S.windows(S.session("genuine", people[0], rng, 60))]
    imp = [profiles[0].match(window_features(w))[0] for w in S.windows(S.session("genuine", people[1], rng, 60))]
    assert np.nanmean(gen) > np.nanmean(imp) + 0.2


def test_bot_and_remote_detected_without_profile(world):
    rng, people, _ = world
    bot = window_features(S.windows(S.session("bot", people[0], rng, 30))[0])
    rat = window_features(S.windows(S.session("rat", people[0], rng, 30, intruder=people[1]))[0])
    human = window_features(S.windows(S.session("genuine", people[0], rng, 30))[0])
    assert bot_signals(bot) and len(remote_signals(rat)) >= 2
    assert not bot_signals(human) and not remote_signals(human)


def test_coaching_signals():
    ev = [{"t": 0, "type": "mu"}, {"t": 6000, "type": "kd", "k": "digit", "f": "account"},
          {"t": 7000, "type": "mu"}, {"t": 15000, "type": "kd", "k": "digit", "f": "amount"},
          {"t": 16000, "type": "paste", "f": "account"}]
    out = coaching_signals(ev, {})
    assert any("pasted" in o for o in out) and any("long waits" in o for o in out)


def test_session_gating(world):
    rng, people, profiles = world
    decisions = {}
    for kind in ("genuine", "bot", "rat", "coached"):
        s = Session("u", profiles[0])
        for w in S.windows(S.session(kind, people[0], rng, 75, intruder=people[2])):
            s.observe(w)
        decisions[kind] = s.gate("transfer", 10_000)["decision"]
    assert decisions["bot"] == "deny" and decisions["rat"] == "deny"
    assert decisions["coached"] in ("hold", "deny", "step_up")
    assert decisions["genuine"] in ("allow", "step_up")


def test_api_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("BEHAVAUTH_DB", str(tmp_path / "t.db"))
    import importlib

    import behavauth.api as api

    importlib.reload(api)
    c = TestClient(api.app)
    rng = np.random.default_rng(1)
    p = S.person(rng)
    for w in S.windows(S.session("genuine", p, rng, 120)):
        r = c.post("/api/enroll", json={"user": "asha", "events": w})
        assert r.status_code == 200
    assert c.get("/api/users/asha").json()["ready"]
    sid = c.post("/api/session", json={"user": "asha"}).json()["session_id"]
    bot = S.windows(S.session("bot", p, rng, 20))[0]
    a = c.post(f"/api/session/{sid}/events", json={"events": bot}).json()
    assert a["action"] == "block"
    assert c.post(f"/api/session/{sid}/action", json={"kind": "transfer", "amount": 5000}).json()["decision"] == "deny"
    assert c.get("/api/sessions").json()[0]["timeline"]
