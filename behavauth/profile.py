"""Per-user behavioural profile and window scoring.

Keystroke and mouse habits are modelled separately with a scaled-Manhattan distance
(robust centre and spread per feature), the detector that performed best in Killourhy
& Maxion's keystroke-dynamics benchmark and that needs no impostor data. Each user's
own enrollment windows set their personal acceptance threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import KEY_FEATURES, MOUSE_FEATURES, vector

MIN_WINDOWS = 6
# features that identify the device or channel rather than the person; used by the
# threat rules, not by the identity model
CHANNEL = {"sample_ms_median", "sample_ms_std", "jump_rate"}


@dataclass
class Modality:
    keys: list[str]
    center: np.ndarray = None
    spread: np.ndarray = None
    threshold: float = float("nan")

    def fit(self, rows: np.ndarray) -> "Modality":
        self.center = np.nanmedian(rows, axis=0)
        mad = np.nanmedian(np.abs(rows - self.center), axis=0) * 1.4826
        floor = np.nanmedian(np.abs(self.center)) * 0.02 + 1e-6
        self.spread = np.where(np.isnan(mad) | (mad < floor), np.maximum(np.abs(self.center) * 0.15, floor), mad)
        # leave-one-out distances of the user's own windows set the personal threshold
        own = []
        for i in range(len(rows)):
            rest = np.delete(rows, i, axis=0)
            c = np.nanmedian(rest, axis=0)
            own.append(self._dist(rows[i], c))
        own = np.array([d for d in own if np.isfinite(d)])
        self.threshold = float(np.percentile(own, 95)) if len(own) else float("nan")
        return self

    def _dist(self, x: np.ndarray, center: np.ndarray) -> float:
        ok = ~np.isnan(x) & ~np.isnan(center)
        if ok.sum() < max(3, len(self.keys) // 3):
            return float("nan")
        return float(np.mean(np.abs(x[ok] - center[ok]) / self.spread[ok]))

    def distance(self, x: np.ndarray) -> float:
        return self._dist(x, self.center)


@dataclass
class Profile:
    user: str
    windows: list[dict] = field(default_factory=list)
    key: Modality | None = None
    mouse: Modality | None = None

    @property
    def ready(self) -> bool:
        return len(self.windows) >= MIN_WINDOWS and self.key is not None

    def fit(self) -> "Profile":
        mkeys = [k for k in MOUSE_FEATURES if k not in CHANNEL]
        self.key = Modality(KEY_FEATURES).fit(np.array([vector(w, KEY_FEATURES) for w in self.windows]))
        self.mouse = Modality(mkeys).fit(np.array([vector(w, mkeys) for w in self.windows]))
        return self

    def match(self, feats: dict) -> tuple[float, dict]:
        """Probability-like score that the window came from this user, plus per-modality detail."""
        out, parts = {}, []
        for name, m in (("keystroke", self.key), ("mouse", self.mouse)):
            d = m.distance(vector(feats, m.keys))
            if np.isfinite(d) and np.isfinite(m.threshold) and m.threshold > 0:
                r = d / m.threshold
                p = 1 / (1 + np.exp(6 * (r - 1.15)))
                out[name] = {"distance_ratio": round(float(r), 2), "match": round(float(p), 3)}
                parts.append(p)
        return (float(np.exp(np.mean(np.log(np.clip(parts, 1e-4, 1))))) if parts else float("nan")), out
