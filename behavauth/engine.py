"""Continuous trust: every window of behaviour updates a session trust score, and
sensitive actions are gated on it."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .features import window_features
from .profile import Profile
from .threats import bot_signals, coaching_signals, remote_signals

START_TRUST = 0.75   # after a successful password/OTP login
DECAY = 0.55         # weight of the previous trust in each update
STEP_UP_BELOW = 0.55
END_BELOW = 0.30


@dataclass
class Assessment:
    trust: float
    match: float | None
    action: str  # allow | step_up | block
    flags: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class Session:
    user: str
    profile: Profile | None
    trust: float = START_TRUST
    flags: dict = field(default_factory=lambda: {"bot": [], "remote": [], "coaching": []})
    history: list[dict] = field(default_factory=list)

    def observe(self, events: list[dict]) -> Assessment:
        f = window_features(events)
        bot, remote, coach = bot_signals(f), remote_signals(f), coaching_signals(events, f)
        match, detail = (None, {})
        if self.profile is not None and self.profile.ready:
            m, detail = self.profile.match(f)
            match = None if math.isnan(m) else m
        if match is not None:
            self.trust = DECAY * self.trust + (1 - DECAY) * match
        if bot:
            self.trust = min(self.trust, 0.1)
        if len(remote) >= 2:
            self.trust = min(self.trust, 0.25)
        for k, v in (("bot", bot), ("remote", remote), ("coaching", coach)):
            for r in v:
                if r not in self.flags[k]:
                    self.flags[k].append(r)

        reasons = []
        if match is not None and match < 0.3:
            worst = min(detail.items(), key=lambda kv: kv[1]["match"])[0] if detail else "behaviour"
            reasons.append(f"{worst} rhythm does not match {self.user}'s profile")
        reasons += bot + remote + coach
        if bot or self.trust < END_BELOW:
            action = "block"
        elif remote or self.trust < STEP_UP_BELOW:
            action = "step_up"
        else:
            action = "allow"
        a = Assessment(round(self.trust, 3), None if match is None else round(match, 3), action,
                       {k: list(v) for k, v in self.flags.items()}, detail, reasons)
        self.history.append({"trust": a.trust, "match": a.match, "action": action, "reasons": reasons})
        return a

    def gate(self, kind: str, amount: float = 0.0) -> dict:
        """Decide a sensitive action (transfer, add payee, change phone) with what we know now."""
        if self.flags["bot"]:
            return {"decision": "deny", "why": "automated input detected in this session"}
        if self.flags["remote"]:
            return {"decision": "deny", "why": "this session appears to be remotely controlled; payments are paused. "
                                               "If someone asked you to install a screen-sharing app, hang up and call your bank."}
        if self.flags["coaching"] and kind in ("transfer", "add_payee"):
            return {"decision": "hold", "why": "Are you on a call with someone telling you what to type? Banks, police and "
                                               "courier companies never ask you to move money. We've paused this for 4 hours."}
        if self.trust < END_BELOW:
            return {"decision": "deny", "why": "behaviour does not match the account owner"}
        if not self.history and kind in ("transfer", "add_payee", "change_phone"):
            return {"decision": "step_up", "why": "not enough interaction seen yet to vouch for this session"}
        if self.trust < STEP_UP_BELOW or (kind == "transfer" and amount >= 50_000 and self.trust < 0.7):
            return {"decision": "step_up", "why": "confirm it's you with device biometrics or OTP"}
        return {"decision": "allow", "why": "behaviour consistent with the account owner"}
