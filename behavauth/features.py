"""Turn raw interaction events into behavioural features.

Event format (sent by web/capture.js, produced by the simulator):
    {"t": ms, "type": "kd"|"ku", "k": key class, "f": field, "i": position in field}
    {"t": ms, "type": "mm", "x": px, "y": px}            pointer move
    {"t": ms, "type": "md"|"mu", "x": px, "y": px}       pointer down / up
    {"t": ms, "type": "paste"|"focus"|"blur", "f": field}
    {"t": ms, "type": "vis", "v": "hidden"|"visible"}
Key *classes* (letter, digit, space, back, shift, other) are recorded, never the
characters themselves, so no typed content is collected.
"""
from __future__ import annotations

import math

import numpy as np

KEY_FEATURES = ["dwell_mean", "dwell_std", "dwell_median", "flight_mean", "flight_std", "dd_mean", "dd_std",
                "typing_rate", "backspace_rate", "long_pause_rate", "shift_dwell"]
MOUSE_FEATURES = ["speed_mean", "speed_std", "speed_p90", "accel_mean", "accel_std", "curvature_mean", "straightness",
                  "pause_rate", "click_ms_mean", "move_to_click_ms", "sample_ms_median", "sample_ms_std", "jump_rate",
                  "angle_entropy"]
FEATURES = KEY_FEATURES + MOUSE_FEATURES


def _nan(n):
    return {k: float("nan") for k in n}


def keystroke_features(events: list[dict]) -> dict:
    downs, out = {}, []
    seq = []  # (down_t, up_t, class, field)
    for e in events:
        if e["type"] == "kd":
            downs.setdefault((e.get("k"), e.get("f"), e.get("i")), e["t"])
        elif e["type"] == "ku":
            key = (e.get("k"), e.get("f"), e.get("i"))
            if key in downs:
                seq.append((downs.pop(key), e["t"], e.get("k"), e.get("f")))
    if len(seq) < 5:
        return _nan(KEY_FEATURES)
    seq.sort()
    d = np.array([s[1] - s[0] for s in seq], float)
    dn = np.array([s[0] for s in seq], float)
    up = np.array([s[1] for s in seq], float)
    flight = dn[1:] - up[:-1]
    same_field = np.array([a[3] == b[3] for a, b in zip(seq, seq[1:])])
    dd = np.diff(dn)[same_field]  # gaps between fields are navigation, not typing
    typing = dd[dd < 1500]
    span = (dn[-1] - dn[0]) / 1000
    shift = [s[1] - s[0] for s in seq if s[2] == "shift"]
    out = {
        "dwell_mean": d.mean(), "dwell_std": d.std(), "dwell_median": float(np.median(d)),
        "flight_mean": float(np.mean(flight[flight < 1500])) if (flight < 1500).any() else float("nan"),
        "flight_std": float(np.std(flight[flight < 1500])) if (flight < 1500).sum() > 1 else float("nan"),
        "dd_mean": float(typing.mean()) if len(typing) else float("nan"),
        "dd_std": float(typing.std()) if len(typing) > 1 else float("nan"),
        "typing_rate": len(seq) / span if span > 0 else float("nan"),
        "backspace_rate": sum(1 for s in seq if s[2] == "back") / len(seq),
        "long_pause_rate": float((dd > 1500).mean()) if len(dd) else 0.0,
        "shift_dwell": float(np.mean(shift)) if shift else float("nan"),
    }
    return {k: float(v) for k, v in out.items()}


def mouse_features(events: list[dict]) -> dict:
    mv = [e for e in events if e["type"] == "mm"]
    if len(mv) < 15:
        return _nan(MOUSE_FEATURES)
    t = np.array([e["t"] for e in mv], float)
    x = np.array([e["x"] for e in mv], float)
    y = np.array([e["y"] for e in mv], float)
    dt = np.diff(t)
    dx, dy = np.diff(x), np.diff(y)
    dist = np.hypot(dx, dy)
    moving = (dt > 0) & (dt < 200)
    speed = dist[moving] / dt[moving]  # px/ms
    accel = np.diff(speed) / np.maximum(dt[moving][1:], 1) if len(speed) > 2 else np.array([0.0])
    ang = np.arctan2(dy, dx)
    turn = np.abs(np.angle(np.exp(1j * np.diff(ang))))
    seg_len = dist[1:] + 1e-9
    curvature = turn / seg_len

    # strokes: runs of movement separated by >150 ms pauses
    breaks = np.where(dt > 150)[0]
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(mv) - 1]
    straight = []
    for s, e in zip(starts, ends):
        if e - s >= 4:
            path = dist[s:e].sum()
            if path > 20:
                straight.append(math.hypot(x[e] - x[s], y[e] - y[s]) / path)
    hist, _ = np.histogram(ang[dist > 1], bins=8, range=(-np.pi, np.pi))
    p = hist / max(hist.sum(), 1)
    entropy = float(-(p[p > 0] * np.log2(p[p > 0])).sum())

    downs = {e["t"]: e for e in events if e["type"] == "md"}
    ups = [e for e in events if e["type"] == "mu"]
    click_ms, approach = [], []
    for u in ups:
        prior = [dt_ for dt_ in downs if dt_ <= u["t"]]
        if prior:
            click_ms.append(u["t"] - max(prior))
    for d_t in downs:
        before = t[t <= d_t]
        if len(before):
            approach.append(d_t - before.max())
    return {
        "speed_mean": float(speed.mean()) if len(speed) else float("nan"),
        "speed_std": float(speed.std()) if len(speed) else float("nan"),
        "speed_p90": float(np.percentile(speed, 90)) if len(speed) else float("nan"),
        "accel_mean": float(np.mean(np.abs(accel))), "accel_std": float(np.std(accel)),
        "curvature_mean": float(np.median(curvature)) if len(curvature) else float("nan"),
        "straightness": float(np.median(straight)) if straight else float("nan"),
        "pause_rate": len(breaks) / max((t[-1] - t[0]) / 1000, 1e-3),
        "click_ms_mean": float(np.mean(click_ms)) if click_ms else float("nan"),
        "move_to_click_ms": float(np.median(approach)) if approach else float("nan"),
        "sample_ms_median": float(np.median(dt[dt > 0])) if (dt > 0).any() else float("nan"),
        "sample_ms_std": float(np.std(dt[(dt > 0) & (dt < 200)])) if ((dt > 0) & (dt < 200)).any() else float("nan"),
        "jump_rate": float(np.mean(dist > 250)), "angle_entropy": entropy,
    }


def window_features(events: list[dict]) -> dict:
    return {**keystroke_features(events), **mouse_features(events)}


def vector(f: dict, keys=FEATURES) -> np.ndarray:
    return np.array([f.get(k, float("nan")) for k in keys], float)
