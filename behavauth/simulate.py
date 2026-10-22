"""Synthetic interaction sessions for evaluation.

Each simulated person has stable habits: how long they hold keys, how quickly they
move between them, how fast and how curved their mouse movements are, how long they
press the button. Threat sessions reproduce what the detectors look for:

impostor   another human with their own habits, logged in with stolen credentials
bot        scripted input: constant key timing, straight constant-speed moves, instant clicks
rat        a fraudster driving the victim's machine through a remote-access app (AnyDesk-style):
           their own habits, coarse bursty mouse sampling, near-zero key dwell from injected input
coached    the genuine customer, but on a call with a scammer: long hesitations while
           listening, digits pasted into the payee field, slower and erratic typing
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

KEY_MIX = (["letter"] * 14) + ["digit"] * 3 + ["space"] * 3 + ["shift"]


@dataclass
class Person:
    dwell: float
    dwell_sd: float
    flight: float
    flight_sd: float
    backspace: float
    speed: float        # px/ms peak
    curve: float        # control-point offset ratio
    tremor: float       # px noise
    sample_ms: float    # device pointer rate
    click_ms: float
    approach_ms: float


def person(rng) -> Person:
    return Person(dwell=rng.normal(100, 22), dwell_sd=rng.uniform(10, 28), flight=rng.normal(115, 45),
                  flight_sd=rng.uniform(30, 70), backspace=rng.uniform(0.01, 0.07), speed=rng.uniform(0.7, 2.4),
                  curve=rng.uniform(0.04, 0.32), tremor=rng.uniform(0.3, 1.6), sample_ms=rng.choice([8.0, 16.7]),
                  click_ms=rng.normal(100, 22), approach_ms=rng.uniform(80, 320))


def _type(rng, p: Person, t: float, n: int, field: str, *, bot=False, injected=False, coached=False) -> tuple[list, float]:
    ev = []
    for i in range(n):
        k = "back" if rng.random() < p.backspace else KEY_MIX[rng.integers(len(KEY_MIX))]
        if bot:
            dwell, gap = 50.0 + rng.normal(0, 0.5), 60.0 + rng.normal(0, 0.5)
        else:
            dwell = max(15.0, rng.normal(p.dwell, p.dwell_sd) * (1.5 if k == "shift" else 1.0))
            gap = rng.normal(p.flight, p.flight_sd)
            if injected:
                dwell = abs(rng.normal(4, 2))
            if coached and rng.random() < 0.25:
                gap += rng.uniform(800, 2500)  # waiting for the caller to read the next digits
            if rng.random() < 0.03:
                gap += rng.uniform(1500, 4000)  # ordinary thinking pause
        ev.append({"t": t, "type": "kd", "k": k, "f": field, "i": i})
        ev.append({"t": t + dwell, "type": "ku", "k": k, "f": field, "i": i})
        t += dwell + max(gap, -dwell * 0.6)
    return ev, t


def _move(rng, p: Person, t: float, a, b, *, bot=False, rat=False) -> tuple[list, float]:
    ev = []
    a, b = np.array(a, float), np.array(b, float)
    dist = np.linalg.norm(b - a)
    dur = 120 + dist / (p.speed * (1.0 if not bot else 1.2)) * 1.9
    if bot:
        step, ctrl = 16.0, (a + b) / 2
    else:
        normal = np.array([-(b - a)[1], (b - a)[0]]) / (dist + 1e-9)
        ctrl = (a + b) / 2 + normal * dist * p.curve * rng.choice([-1, 1])
        step = 33.0 if rat else p.sample_ms  # remote tools forward the cursor per video frame
    n = max(int(dur / step), 3)
    for j in range(1, n + 1):
        s = j / n
        tau = s if bot else 10 * s**3 - 15 * s**4 + 6 * s**5  # minimum-jerk timing for humans
        pt = (1 - tau) ** 2 * a + 2 * (1 - tau) * tau * ctrl + tau**2 * b
        if not bot:
            pt += rng.normal(0, p.tremor, 2)
        dt = step if bot else (step + rng.exponential(14) if rat else step + rng.normal(0, 0.8))
        t += dt
        if rat and rng.random() < 0.35:
            continue  # remote tool drops/coalesces samples: bursts with gaps
        ev.append({"t": t, "type": "mm", "x": round(float(pt[0]), 1), "y": round(float(pt[1]), 1)})
    return ev, t


def session(kind: str, owner: Person, rng, seconds: float = 60.0, intruder: Person | None = None) -> list[dict]:
    """A banking session: move to fields, click, type, submit, repeat."""
    p = intruder if kind in ("impostor", "rat") else owner
    bot, rat, coached = kind == "bot", kind == "rat", kind == "coached"
    ev, t = [], 0.0
    pos = np.array([600.0, 400.0])
    fields = ["payee", "account", "ifsc", "amount", "note", "search", "message"]
    while t < seconds * 1000:
        target = np.array([rng.uniform(80, 1200), rng.uniform(80, 700)])
        if rat and rng.random() < 0.3:  # remote cursor jumps
            pos = target + rng.normal(0, 3, 2)
            ev.append({"t": t, "type": "mm", "x": float(pos[0]), "y": float(pos[1])})
        else:
            mv, t = _move(rng, p, t, pos, target, bot=bot, rat=rat)
            ev += mv
            pos = target
        t += 2.0 if bot else rng.uniform(0.6, 1.4) * p.approach_ms
        ev.append({"t": t, "type": "md", "x": float(pos[0]), "y": float(pos[1])})
        click = 3.0 if bot else (abs(rng.normal(8, 3)) if rat else max(30.0, rng.normal(p.click_ms, 15)))
        t += click
        ev.append({"t": t, "type": "mu", "x": float(pos[0]), "y": float(pos[1])})
        field = fields[rng.integers(len(fields))]
        if coached and rng.random() < 0.35:
            t += rng.uniform(5000, 15000)  # listening to the caller
        if coached and field == "account" and rng.random() < 0.7:
            ev.append({"t": t, "type": "paste", "f": field})
            t += 400
            continue
        t += rng.uniform(150, 600)
        typed, t = _type(rng, p, t, int(rng.integers(6, 24)), field, bot=bot, injected=rat, coached=coached)
        ev += typed
        t += 50 if bot else rng.uniform(200, 900)
    return [e for e in ev if e["t"] <= seconds * 1000]


def windows(events: list[dict], size_ms: float = 15_000) -> list[list[dict]]:
    if not events:
        return []
    end = events[-1]["t"]
    return [[e for e in events if w <= e["t"] < w + size_ms] for w in np.arange(0, end, size_ms)]
