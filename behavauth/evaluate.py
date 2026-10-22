"""Benchmark on simulated users: identity accuracy (EER) and threat detection."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_curve

from . import simulate as S
from .engine import Session
from .features import window_features
from .profile import Profile


def eer(genuine: list[float], impostor: list[float]) -> tuple[float, np.ndarray, np.ndarray]:
    y = np.r_[np.ones(len(genuine)), np.zeros(len(impostor))]
    s = np.r_[genuine, impostor]
    fpr, tpr, _ = roc_curve(y, s)
    fnr = 1 - tpr
    i = int(np.nanargmin(np.abs(fnr - fpr)))
    return float((fpr[i] + fnr[i]) / 2), fpr, fnr


def run(n_users: int = 30, enroll_sessions: int = 3, seed: int = 0, out: str = "results") -> dict:
    rng = np.random.default_rng(seed)
    people = [S.person(rng) for _ in range(n_users)]
    profiles = []
    for p in people:
        ws = [window_features(w) for _ in range(enroll_sessions) for w in S.windows(S.session("genuine", p, rng, 60))]
        profiles.append(Profile("u", ws).fit())

    scores = {"keystroke": ([], []), "mouse": ([], []), "fused": ([], [])}
    for i, p in enumerate(people):
        gen = [window_features(w) for w in S.windows(S.session("genuine", p, rng, 60))]
        imp = []
        for j in rng.choice([k for k in range(n_users) if k != i], 3, replace=False):
            imp += [window_features(w) for w in S.windows(S.session("genuine", people[j], rng, 30))]
        for feats, slot in ((gen, 0), (imp, 1)):
            for f in feats:
                m, d = profiles[i].match(f)
                if np.isfinite(m):
                    scores["fused"][slot].append(m)
                for mod in ("keystroke", "mouse"):
                    if mod in d:
                        scores[mod][slot].append(d[mod]["match"])

    session_rows = {}
    time_to_catch = []
    for kind in ("genuine", "impostor", "bot", "rat", "coached"):
        decisions = []
        for i, p in enumerate(people):
            s = Session("u", profiles[i])
            caught_at = None
            for k, w in enumerate(S.windows(S.session(kind, p, rng, 90, intruder=people[(i + 7) % n_users]))):
                a = s.observe(w)
                if caught_at is None and a.action != "allow":
                    caught_at = (k + 1) * 15
            decisions.append(s.gate("transfer", 20_000)["decision"])
            if kind == "impostor" and caught_at:
                time_to_catch.append(caught_at)
        session_rows[kind] = {d: decisions.count(d) / len(decisions) for d in ("allow", "step_up", "hold", "deny")}

    res = {"users": n_users, "eer": {}, "sessions": session_rows,
           "impostor_median_seconds_to_flag": float(np.median(time_to_catch)) if time_to_catch else None}
    Path(out).mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for name, (g, im) in scores.items():
        e, fpr, fnr = eer(g, im)
        res["eer"][name] = e
        ax[0].plot(fpr, fnr, label=f"{name} (EER {e:.1%})")
    ax[0].set_xscale("log")
    ax[0].set_xlim(1e-3, 1)
    ax[0].set_xlabel("false accept rate")
    ax[0].set_ylabel("false reject rate")
    ax[0].set_title("Per-window identity (15 s of behaviour)")
    ax[0].legend()
    kinds = list(session_rows)
    bottom = np.zeros(len(kinds))
    for d, c in (("allow", "#2a9d8f"), ("step_up", "#e9c46a"), ("hold", "#f4a261"), ("deny", "#e76f51")):
        vals = np.array([session_rows[k][d] for k in kinds])
        ax[1].bar(kinds, vals, bottom=bottom, label=d, color=c)
        bottom += vals
    ax[1].set_title("Decision on a ₹20,000 transfer after 90 s")
    ax[1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(out) / "summary.png", dpi=130)
    (Path(out) / "results.json").write_text(json.dumps(res, indent=2))
    return res
