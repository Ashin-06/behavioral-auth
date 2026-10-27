# Behaviour Guard

Continuous authentication for online banking, based on *how* someone types and moves the pointer, not on *what* they type. It runs silently after login and answers three questions:

1. **Is this still the account owner?** Each user has a personal behavioural profile, checked every 15 seconds.
2. **Is a machine or a remote operator driving the session?** Bots and remote-access tools such as AnyDesk are caught from the very first session, with no profile needed.
3. **Is the real customer being coached by a scammer on the phone?** Long silences before typing each field, and payee details pasted rather than typed.

Passwords and OTPs stop none of these. A stolen password passes the login screen. Screen-sharing fraud happens *inside* a genuine session. A coached victim passes every check, because it really is them.

## What it measures

The browser capture script records **timing and movement only**. For keys it stores the *class* (letter, digit, space, backspace, shift), never the character, so no password, account number or message text is collected.

| Keystroke features | Pointer features |
|---|---|
| hold (dwell) time mean/std/median, key-to-key flight, down-to-down latency within a field, typing rate, backspace rate, pause rate, shift hold | speed mean/std/p90, acceleration, curvature, stroke straightness, pauses, click duration, approach-to-click time, sampling interval and jitter, cursor jumps, direction entropy |

**Identity model.** A per-user scaled-Manhattan distance, one per modality: robust centre and spread per feature. This detector scored best in Killourhy & Maxion's keystroke benchmark and needs no impostor data. Each user's own enrollment windows set their personal threshold by leave-one-out. Keystroke and mouse matches are fused, and session trust is updated as a running blend, so a single odd window doesn't lock anyone out.

**Profile-free threat rules:**

| Threat | Tell-tale |
|---|---|
| Bot / scripted input | key hold times varying by < 3 ms, perfectly regular rhythm, perfectly straight mouse paths, machine-exact timing, 3 ms clicks |
| Remote-access tool | pointer updates arriving in video-frame bursts (~30–60 ms), cursor teleports, near-zero key hold times from injected input |
| Coached victim | beneficiary details pasted, repeated 4 s+ silences between opening a field and typing in it |

**Decisions.** For a sensitive action (transfer, add payee, change phone) the session returns allow / step-up (biometric or OTP) / hold / deny, each with a plain-language reason. A coached victim gets a hold with a direct question: *"Are you on a call with someone telling you what to type?"*

## Results

`python -m behavauth evaluate`: 30 simulated users, each with their own typing and mouse habits. Profiles come from three 1-minute sessions.

![results](results/summary.png)

| | |
|---|---|
| Identity from **15 s** of behaviour (EER) | keystroke 18.3% · mouse 14.1% · **fused 10.7%** |
| Genuine users, ₹20,000 transfer after 90 s | 90% allowed, 10% asked to step up, **0% denied** |
| Impostor with the right password | **77% denied**, 13% step-up, 10% allowed; median **15 s** to first flag |
| Bot sessions | **100% denied** |
| Remote-access takeover | **100% denied** |
| Coached victim | **97% stopped** (50% hold with a scam warning, 40% denied, 7% step-up) |

One 15-second window is weak evidence, which is why EER per window is around 11%. Trust accumulates across windows, and that is how the session-level numbers get much higher. The simulator models real effects (minimum-jerk pointer motion, device sampling rates, remote-desktop frame pacing), but real users are messier. Calibrate on your own traffic, then tune `STEP_UP_BELOW` / `END_BELOW` in `engine.py` and the per-user threshold percentile in `profile.py`.

### On real people

The simulator can't tell you how real people behave, so the same identity model, with no impostor data at enrolment, is also scored on two public datasets (`python -m behavauth realdata`, results in `results/real_data.json`):

| Dataset | What is scored | Result |
|---|---|---|
| [CMU keystroke benchmark](https://www.cs.cmu.edu/~keystroke/) (51 people, 400 typings each) | per-key timings, the paper's protocol | **8.9% EER** (the paper's scaled-Manhattan detector: 9.6%) |
| same | the content-free class features this service actually stores, 5 typings per window | **10.3% EER** |
| [Balabit mouse challenge](https://github.com/balabit/Mouse-Dynamics-Challenge) (10 users, 816 labelled test sessions, 405 by intruders) | is this session the account owner? mouse only | **AUC 0.72**, 32.7% EER |

The keystroke model holds up on real typists, and dropping the actual keys in favour of key classes costs little. Mouse movement on its own is weak: Balabit sessions are short, recorded over remote desktop, and the model never sees intruder data. Treat the mouse signal as supporting evidence that is fused with typing and the threat rules, never as a sole identity check.

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q                  # 33 tests
python -m behavauth evaluate         # benchmark -> results/
python -m behavauth realdata --cmu DSL-StrongPasswordData.csv --balabit Mouse-Dynamics-Challenge/
python -m behavauth seed             # fill the analyst view with example sessions
python -m behavauth serve            # http://127.0.0.1:8007 (demo mode, no keys)
```

In a container (production mode; see [docs/runbook.md](docs/runbook.md)):

```bash
docker build -t behavioral-auth:1.0.0 .
python -m behavauth.ops keygen       # an API key with its hash
docker run -p 8007:8007 -v behavauth-data:/data -e BEHAVAUTH_KEYS_FILE=/run/secrets/behavauth-keys.json behavioral-auth:1.0.0
```

- **http://127.0.0.1:8007**: a demo bank.
  1. Choose a username and run **Teach it my behaviour** for about 2 minutes: retype sentences and click a moving dot.
  2. Sign in and fill the transfer form. The side panel shows trust, per-modality match and any flags live.
  3. Ask someone else to use your username and watch trust fall.
- **http://127.0.0.1:8007/analyst**: every session with its trust timeline and reasons.

## Integrating

1. Add `web/capture.js` to your pages. Every 10–15 s, post `Behaviour.take()` to `/api/session/{id}/events`.
2. Before a sensitive action, call `/api/session/{id}/action` with `{"kind": "transfer", "amount": ...}`.
3. Enroll users passively from their first few genuine sessions (`/api/enroll`), or with a short guided exercise like the demo's.

| Endpoint | Purpose |
|---|---|
| `POST /api/enroll` | `{user, events}`: add one window to the user's profile |
| `GET /api/users/{user}` | enrollment progress |
| `POST /api/session` | `{user}`: start monitoring |
| `POST /api/session/{id}/events` | `{events}`: returns trust, match, action, flags, reasons |
| `POST /api/session/{id}/action` | `{kind, amount}`: allow / step_up / hold / deny with reason |
| `GET /api/sessions` | analyst feed |
| `GET /healthz`, `/readyz`, `/metrics` | liveness, readiness (database), Prometheus metrics (role `monitor`) |

Profiles and session logs are stored in SQLite or Postgres (`BEHAVAUTH_DATABASE_URL`; the older `BEHAVAUTH_DB` file path still works, and its database upgrades in place). The default in development is `data/behavauth.db`. A live session's trust score is kept in the process that started it: after a restart, or on another replica, the client starts a new session, and sensitive actions step up until enough behaviour has been seen again. Run one replica or sticky sessions.

| Setting | Purpose |
|---|---|
| `BEHAVAUTH_API_KEYS` / `BEHAVAUTH_KEYS_FILE` | API keys as `{"sha256:<hex>": {"user", "role"}}`, sent as `X-API-Key` or `Authorization: Bearer`. Roles: `bank_backend` (all `/api` calls except the feed), `analyst` (`/api/sessions`), `monitor` (`/metrics`), `admin`. Without keys the service runs in demo mode on loopback only |
| `BEHAVAUTH_ENV` | `production` refuses to start without hashed keys and a database URL |
| `BEHAVAUTH_SESSION_IDLE_S` | drop monitoring sessions idle for longer than this (default 7200 s) |

The full list is in [docs/runbook.md](docs/runbook.md). The demo pages ask for a key once when the service has keys; in production your back end relays the events with its own key.

## Layout

```
behavauth/
  features.py   keystroke + pointer features from raw events
  profile.py    per-user scaled-Manhattan model with personal thresholds
  threats.py    bot, remote-access and coaching rules
  engine.py     session trust and action gating
  simulate.py   synthetic people, impostors, bots, remote takeovers, coached victims
  evaluate.py   EER curves and session decisions
  realdata.py   scoring on the CMU keystroke and Balabit mouse datasets
  store.py      SQLite / Postgres persistence (db.py, migrations/)
  ops.py        settings, API keys and roles, limits, logs, metrics, health
  api.py        FastAPI service
web/            capture.js, demo bank, analyst view
```

## Privacy

Behavioural data is biometric data in many jurisdictions; India's DPDP Act treats it as personal data. Tell users about it, keep only feature vectors (this service never stores raw event streams), set a retention period, and let users reset their profile.

## Production readiness

**In place** (see [docs/runbook.md](docs/runbook.md), [docs/threat-model.md](docs/threat-model.md) and [docs/model-card.md](docs/model-card.md)):
- Pinned dependencies (`requirements.lock`), `pyproject.toml`, a container image that runs as a non-root user with a health check, and CI (ruff, bandit, pip-audit, tests with coverage).
- Production mode that refuses to start without hashed per-client API keys and a database, and no public listener without keys. `seed` (simulated users) refuses to run in production.
- Roles on keys (the analyst feed is separate from scoring), per-client rate limits, a body size cap, security headers, CORS only for listed origins, and errors that don't echo input.
- Enrollments and session logs in SQLite or Postgres, with numbered migrations; old `BEHAVAUTH_DB` files upgrade in place; profiles refit when another replica adds enrollment windows.
- JSON logs with request IDs, `/healthz`, `/readyz` and Prometheus metrics, including counts of window and action decisions.

**Still needed before it gates real payments**, none of which code can supply:
- An independent security review and penetration test, including attempts to replay or synthesise a customer's behaviour. Nobody outside this project has reviewed it.
- Validation on the bank's own customers and devices. The session numbers come from simulated users; on real data the keystroke model is close to the published benchmark, but mouse alone reaches only AUC 0.72 on Balabit.
- RBI and DPDP Act 2023 sign-off: behavioural data is personal (in many places biometric) data, so consent, notice, a retention period, profile reset and a fairness check across ages, abilities and devices are needed.
- Real integrations: the bank's login and step-up (device biometrics, OTP), its fraud case system for holds, and session state shared across replicas.
- TLS and a shared rate limiter at the ingress; an on-call team with SLOs and alerting on the metrics above.
