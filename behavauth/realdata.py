"""Evaluate the identity model on public real-world datasets.

CMU keystroke benchmark (Killourhy & Maxion, DSN 2009)
    51 people each typed the password ".tie5Roanl" 400 times over 8 sessions.
    https://www.cs.cmu.edu/~keystroke/  -  DSL-StrongPasswordData.csv
    Protocol from the paper: enrol on a subject's first 200 repetitions, test on their
    last 200 (genuine) and on the first 5 repetitions of each of the other 50 (impostor);
    report the mean per-subject equal error rate.

Balabit Mouse Dynamics Challenge (2016)
    Mouse events from 10 users working over remote desktop; labelled test sessions are
    either the account owner or someone else using the account.
    https://github.com/balabit/Mouse-Dynamics-Challenge

Both are scored with the same scaled-Manhattan `Modality` used in production, and
without any impostor data at enrolment, which is what a bank has on day one.

    python -m behavauth realdata --cmu DSL-StrongPasswordData.csv --balabit Mouse-Dynamics-Challenge/
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from .evaluate import eer
from .features import KEY_FEATURES, MOUSE_FEATURES, keystroke_features, mouse_features, vector
from .profile import CHANNEL, Modality

# key classes the browser capture would record for ".tie5Roanl" + Enter (content is never kept)
CMU_KEYS = ["period", "t", "i", "e", "five", "Shift.r", "o", "a", "n", "l", "Return"]
CMU_CLASS = {"period": "other", "five": "digit", "Shift.r": "shift", "Return": "other"}
WINDOW_REPS = 5  # five typings of the password, about 55 keystrokes, as one scoring window


def _load_cmu(path: str | Path) -> tuple[list[str], dict[str, np.ndarray]]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    timing = [c for c in rows[0] if c[:2] in ("H.", "DD", "UD")]
    by_subject: dict[str, list[list[float]]] = {}
    for r in rows:
        by_subject.setdefault(r["subject"], []).append([float(r[c]) for c in timing])
    return timing, {s: np.array(v) for s, v in by_subject.items()}


def _events(rep: dict[str, float], t0: float) -> list[dict]:
    """Rebuild key-down/key-up events (class only) from one repetition's timings."""
    ev, down = [], t0
    for i, k in enumerate(CMU_KEYS):
        if i:
            down += rep[f"DD.{CMU_KEYS[i - 1]}.{k}"] * 1000
        hold = rep[f"H.{k}"] * 1000
        cls = CMU_CLASS.get(k, "letter")
        ev += [{"t": down, "type": "kd", "k": cls, "f": "pw", "i": i},
               {"t": down + hold, "type": "ku", "k": cls, "f": "pw", "i": i}]
    return ev


def _subject_eers(train: dict[str, np.ndarray], genuine: dict[str, np.ndarray], probes: dict[str, np.ndarray],
                  keys: list[str]) -> list[float]:
    out = []
    for s in train:
        m = Modality(keys).fit(train[s])
        gen = [-m.distance(x) for x in genuine[s]]
        imp = [-m.distance(x) for o in probes if o != s for x in probes[o]]
        out.append(eer(gen, imp)[0])
    return out


def cmu_keystroke(path: str | Path) -> dict:
    timing, data = _load_cmu(path)
    # 1. the classic benchmark: per-key timings of the fixed password
    raw = _subject_eers({s: v[:200] for s, v in data.items()}, {s: v[200:] for s, v in data.items()},
                        {s: v[:5] for s, v in data.items()}, timing)

    # 2. what the bank actually stores: content-free class features over 5-typing windows
    def windows(v: np.ndarray, start: int, stop: int) -> np.ndarray:
        rows = []
        for w in range(start, stop, WINDOW_REPS):
            ev, t0 = [], 0.0
            for rep in v[w:w + WINDOW_REPS]:
                ev += _events(dict(zip(timing, rep)), t0)
                t0 = ev[-1]["t"] + 1200  # a pause between attempts, as on a login page
            rows.append(vector(keystroke_features(ev), KEY_FEATURES))
        return np.array(rows)

    win = {s: windows(v, 0, 400) for s, v in data.items()}
    cls = _subject_eers({s: w[:40] for s, w in win.items()}, {s: w[40:] for s, w in win.items()},
                        {s: w[:1] for s, w in win.items()}, KEY_FEATURES)
    return {
        "dataset": "CMU keystroke benchmark (Killourhy & Maxion 2009)",
        "subjects": len(data),
        "per_key_timings_mean_eer": round(float(np.mean(raw)), 4),
        "per_key_timings_published_scaled_manhattan_eer": 0.096,
        "class_features_5_typings_mean_eer": round(float(np.mean(cls)), 4),
        "class_features_note": "content-free features the bank stores (dwell, flight, rhythm per key class)",
    }


def _balabit_session(path: Path) -> list[dict]:
    ev = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = float(r["client timestamp"]) * 1000
            x, y, state = float(r["x"]), float(r["y"]), r["state"]
            if x > 10_000 or y > 10_000:  # off-screen sentinel rows in the capture
                continue
            kind = {"Move": "mm", "Drag": "mm", "Pressed": "md", "Released": "mu"}.get(state)
            if kind:
                ev.append({"t": t, "type": kind, "x": x, "y": y})
    return ev


def _mouse_windows(ev: list[dict], seconds: float = 15.0) -> list[np.ndarray]:
    keys = [k for k in MOUSE_FEATURES if k not in CHANNEL]
    out, start, cur = [], None, []
    for e in ev:
        if start is None:
            start = e["t"]
        if e["t"] - start > seconds * 1000:
            out.append(vector(mouse_features(cur), keys))
            start, cur = e["t"], []
        cur.append(e)
    if cur:
        out.append(vector(mouse_features(cur), keys))
    return [w for w in out if np.isfinite(w).sum() >= len(keys) // 2]


def balabit_mouse(root: str | Path) -> dict:
    root = Path(root)
    keys = [k for k in MOUSE_FEATURES if k not in CHANNEL]
    labels = {}
    with open(root / "public_labels.csv", newline="") as f:
        for r in csv.DictReader(f):
            labels[r["filename"]] = int(r["is_illegal"])
    y, score, windows_used = [], [], []
    for user_dir in sorted((root / "training_files").iterdir()):
        train = [w for p in sorted(user_dir.iterdir()) for w in _mouse_windows(_balabit_session(p))]
        m = Modality(keys).fit(np.array(train))
        for p in sorted((root / "test_files" / user_dir.name).iterdir()):
            if p.name not in labels:
                continue
            ws = _mouse_windows(_balabit_session(p))
            d = [m.distance(w) for w in ws]
            d = [x for x in d if np.isfinite(x)]
            if not d:
                continue
            y.append(1 - labels[p.name])          # 1 = account owner
            score.append(-float(np.median(d)))    # closer to the profile = more likely the owner
            windows_used.append(len(d))
    y, score = np.array(y), np.array(score)
    return {
        "dataset": "Balabit Mouse Dynamics Challenge (2016)",
        "users": len(list((root / "training_files").iterdir())),
        "labelled_test_sessions_scored": int(len(y)),
        "intruder_sessions": int((y == 0).sum()),
        "median_windows_per_test_session": float(np.median(windows_used)),
        "session_auc": round(float(roc_auc_score(y, score)), 4),
        "session_eer": round(eer(score[y == 1].tolist(), score[y == 0].tolist())[0], 4),
    }
