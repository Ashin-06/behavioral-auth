"""Profile-independent threat signals: these work from the very first session, before a
user has any behavioural profile."""
from __future__ import annotations

import math

import numpy as np


def bot_signals(f: dict) -> list[str]:
    out = []
    if np.isfinite(f.get("dwell_std", math.nan)) and f["dwell_std"] < 3:
        out.append(f"key hold times vary by only {f['dwell_std']:.1f} ms (scripted input)")
    if np.isfinite(f.get("dd_std", math.nan)) and f["dd_std"] < 4:
        out.append("perfectly regular typing rhythm")
    if np.isfinite(f.get("straightness", math.nan)) and f["straightness"] > 0.995 and f.get("curvature_mean", 1) < 1e-3:
        out.append("mouse moves in perfectly straight lines")
    if np.isfinite(f.get("sample_ms_std", math.nan)) and f["sample_ms_std"] < 0.2:
        out.append("machine-exact pointer timing")
    if np.isfinite(f.get("click_ms_mean", math.nan)) and f["click_ms_mean"] < 15 and not (
            np.isfinite(f.get("sample_ms_median", math.nan)) and f["sample_ms_median"] > 25):
        out.append(f"clicks last {f['click_ms_mean']:.0f} ms (too fast for a finger)")
    return out


def remote_signals(f: dict) -> list[str]:
    out = []
    coarse = np.isfinite(f.get("sample_ms_median", math.nan)) and f["sample_ms_median"] > 25
    bursty = np.isfinite(f.get("sample_ms_std", math.nan)) and f["sample_ms_std"] > 9
    if coarse and bursty:
        out.append(f"pointer updates arrive in bursts every ~{f['sample_ms_median']:.0f} ms (remote-desktop pattern)")
    if f.get("jump_rate", 0) > 0.02:
        out.append("cursor teleports across the screen")
    if np.isfinite(f.get("dwell_mean", math.nan)) and f["dwell_mean"] < 15:
        out.append(f"keys held only {f['dwell_mean']:.0f} ms on average (injected keystrokes)")
    if np.isfinite(f.get("click_ms_mean", math.nan)) and f["click_ms_mean"] < 15 and coarse:
        out.append("clicks with no press duration")
    return out


def coaching_signals(events: list[dict], f: dict) -> list[str]:
    """Signs the genuine customer is being talked through a payment by someone else."""
    out = []
    pastes = [e for e in events if e["type"] == "paste" and e.get("f") in ("account", "ifsc", "payee", "upi")]
    if pastes:
        out.append("beneficiary details pasted, not typed")
    # long silences between selecting a field and starting to type in it
    ev = sorted(events, key=lambda e: e["t"])
    waits, last_click = [], None
    for e in ev:
        if e["type"] == "mu":
            last_click = e["t"]
        elif e["type"] == "kd" and last_click is not None:
            if e["t"] - last_click > 4000:
                waits.append(e["t"] - last_click)
            last_click = None
    if len(waits) >= 2:
        out.append(f"{len(waits)} long waits ({np.mean(waits) / 1000:.0f} s) between opening a field and typing (being dictated to?)")
    return out
