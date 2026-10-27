# Model card: Behaviour Guard 1.0.0

Numbers come from `results/results.json`, `results/real_data.json` and the README. The session-level
numbers are from simulated users; nothing here has been measured on a bank's own customers.

## What it is

| Part | Method | Learned? |
|---|---|---|
| Identity | per-user scaled-Manhattan distance, one model for keystroke features and one for pointer features, fused; personal threshold from leave-one-out over the user's own enrollment windows | fitted per user from at least 6 enrollment windows; no impostor data |
| Threat rules | bot, remote-access and coaching signals (`threats.py`) | rules |
| Session trust | running blend of window matches (`DECAY` 0.55), capped by bot and remote signals; step-up below 0.55, end below 0.30 | thresholds |

Features are timing and movement only. Keys are stored as classes (letter, digit, space,
backspace, shift), never characters.

## Intended use

Continuous, silent authentication after a normal login, to decide whether a sensitive action
(transfer, new payee, phone change) can go ahead, needs step-up, should be held or denied. One
signal alongside the bank's login, device binding and fraud monitoring; never a login method on
its own, and never used to identify people across accounts.

## Data

| Data | Used for |
|---|---|
| Simulator (`simulate.py`): 30 users with their own typing and mouse habits, impostors, bots, remote takeovers and coached victims; minimum-jerk pointer motion, device sampling rates, remote-desktop frame pacing | the evaluation below; profiles from three 1-minute sessions |
| CMU keystroke benchmark (Killourhy & Maxion 2009): 51 people, 400 typings each | identity model on real typists |
| Balabit Mouse Dynamics Challenge (2016): 10 users, 816 labelled test sessions, 405 by intruders | identity model on real mouse movement |

## Metrics

**Simulated users** (`python -m behavauth evaluate`; re-run on 27 October 2026 with the locked
dependencies, identical output):

| | |
|---|---|
| Identity from 15 s of behaviour, EER | keystroke 18.3%, mouse 14.1%, fused 10.7% |
| Genuine users, ₹20,000 transfer after 90 s | 90% allowed, 10% step-up, 0% denied |
| Impostor with the right password | 76.7% denied, 13.3% step-up, 10% allowed; median 15 s to first flag |
| Bot sessions | 100% denied |
| Remote-access takeover | 100% denied |
| Coached victim | 50% hold with a scam warning, 40% denied, 6.7% step-up, 3.3% allowed |

**Real people:**

| Dataset | What is scored | Result |
|---|---|---|
| CMU keystroke | per-key timings, the paper's protocol | 8.9% EER (published scaled-Manhattan: 9.6%) |
| CMU keystroke | the content-free class features the service stores, 5 typings per window | 10.3% EER |
| Balabit mouse | is this session the account owner? mouse only, median 15 windows per session | AUC 0.72, EER 32.7% |

## Known failure modes

- One 15-second window is weak evidence (about 11% EER on simulated users); decisions rely on trust
  accumulating over several windows, so the first seconds of a session prove little.
- Mouse movement alone is weak on real data (Balabit AUC 0.72): short sessions recorded over remote
  desktop, and no intruder data at enrollment. Use it only fused with typing and the threat rules.
- A bot replaying recorded human timing, or malware replaying the customer's own behaviour, is not
  caught by the profile-free rules.
- A coached victim who types everything at a normal pace looks like the owner, because it is.
- Injuries, a new keyboard or mouse, a phone instead of a laptop, and accessibility tools change
  behaviour and raise step-ups for genuine customers.

## Caveats

- The session-level numbers come from a simulator; real users are messier. Calibrate on the bank's
  own traffic, then tune `STEP_UP_BELOW` / `END_BELOW` (`engine.py`) and the per-user threshold
  percentile (`profile.py`).
- The real-data results score the identity model only, not the threat rules or the session gating.
- Fairness across ages, motor abilities and devices has not been measured.
