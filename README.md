# Behaviour Guard

Continuous authentication for online banking based on how someone types and moves the pointer, not what they type. It runs quietly after login and answers three questions:

1. Is this still the account owner? Each user has a personal behaviour profile, checked every 15 seconds.
2. Is a bot or a remote operator driving the session? Bots and remote-access tools such as AnyDesk are caught from the first session, without a profile.
3. Is the real customer being coached by a scammer on the phone? Long pauses before each field and pasted payee details are warning signs.

Passwords and OTPs don't help with any of these: a stolen password passes the login screen, screen-sharing fraud happens inside a genuine session, and a coached victim passes every check because it really is them.

## What it measures

The browser script records timing and movement only. For keys it stores the class (letter, digit, space, backspace, shift), never the character, so no password, account number or message text is collected.

- Typing: how long keys are held, the gaps between keys, typing speed, corrections and pauses.
- Pointer: speed, acceleration, curvature, straightness, pauses, clicks, sampling rate and cursor jumps.

Each user's profile is a scaled-Manhattan model, which needs no impostor data and did best in Killourhy and Maxion's keystroke benchmark. Each user gets a personal threshold from their own enrolment data. Typing and pointer scores are combined, and session trust changes gradually so that one odd window doesn't lock anyone out.

Three rules work without a profile:

| Threat | Signs |
|---|---|
| Bot or script | key hold times that barely vary, perfectly regular rhythm, perfectly straight mouse paths |
| Remote-access tool | pointer updates arriving in video-frame bursts, cursor jumps, near-zero key hold times |
| Coached victim | payee details pasted, repeated long pauses between opening a field and typing |

For a sensitive action (transfer, add payee, change phone number) the service returns allow, step-up (biometric or OTP), hold or deny, with a reason. A coached victim gets a hold with a direct question: "Are you on a call with someone telling you what to type?"

## Quick start

```bash
pip install -r requirements.txt
python -m pytest -q                  # 33 tests
python -m behavauth evaluate         # benchmark, written to results/
python -m behavauth seed             # example sessions for the analyst view
python -m behavauth serve            # http://127.0.0.1:8007
```

- `http://127.0.0.1:8007` is a demo bank. Choose a username, spend about two minutes on "Teach it my behaviour", then sign in and fill in the transfer form while the side panel shows trust and flags live. Ask someone else to use your username and watch trust fall.
- `http://127.0.0.1:8007/analyst` lists every session with its trust timeline and reasons.

To run it in a container:

```bash
docker build -t behavioral-auth .
python -m behavauth.ops keygen       # prints an API key and its hash
docker run -p 8007:8007 -v behavauth-data:/data -e BEHAVAUTH_KEYS_FILE=/run/secrets/behavauth-keys.json behavioral-auth
```

## Integrating

1. Add `web/capture.js` to your pages and post `Behaviour.take()` to `/api/session/{id}/events` every 10–15 seconds.
2. Before a sensitive action, call `/api/session/{id}/action` with `{"kind": "transfer", "amount": ...}`.
3. Enrol users from their first few genuine sessions (`/api/enroll`) or with a short guided exercise like the demo's.

| Endpoint | Purpose |
|---|---|
| `POST /api/enroll` | add one window to a user's profile |
| `GET /api/users/{user}` | enrolment progress |
| `POST /api/session` | start monitoring a user |
| `POST /api/session/{id}/events` | returns trust, match, action, flags and reasons |
| `POST /api/session/{id}/action` | allow, step_up, hold or deny with a reason |
| `GET /api/sessions` | analyst feed |
| `GET /healthz`, `/readyz`, `/metrics` | health, readiness and Prometheus metrics |

## Results

| Test | Result |
|---|---|
| Simulated users, impostor with the right password | 77% denied, median 15 s to the first flag |
| Simulated bots and remote-access takeovers | 100% denied |
| Simulated coached victims | 97% stopped |
| Real typists, CMU keystroke benchmark | 8.9% equal error rate (published result 9.6%) |
| Real mouse use, Balabit dataset | AUC 0.72; too weak to use on its own |

Details are in [docs/evaluation.md](docs/evaluation.md). Thresholds should be calibrated on the bank's own traffic: `STEP_UP_BELOW` and `END_BELOW` in `behavauth/engine.py` and the per-user threshold percentile in `behavauth/profile.py`.

## Configuration

| Variable | Purpose |
|---|---|
| `BEHAVAUTH_ENV=production` | refuse to start without hashed API keys and a database |
| `BEHAVAUTH_API_KEYS` / `BEHAVAUTH_KEYS_FILE` | API keys with roles: `bank_backend`, `analyst`, `monitor`, `admin` |
| `BEHAVAUTH_DATABASE_URL` | `sqlite:///...` or `postgresql://...` for profiles and session logs |
| `BEHAVAUTH_SESSION_IDLE_S` | drop sessions idle for longer than this (default 7200 s) |

A live session's trust score is kept in the process that started it, so run one replica or use sticky sessions. All settings: [docs/runbook.md](docs/runbook.md).

## Project layout

```
behavauth/
  features.py   typing and pointer features
  profile.py    per-user model and threshold
  threats.py    bot, remote-access and coaching rules
  engine.py     session trust and action decisions
  simulate.py   simulated users and attacks
  evaluate.py   benchmark
  realdata.py   tests on the CMU and Balabit datasets
  store.py      database storage
  api.py        FastAPI service
web/            capture script, demo bank, analyst view
```

## Privacy

Behaviour data is personal data under India's DPDP Act and biometric data in many other places. Tell users about it, keep only feature vectors (this service never stores raw events), set a retention period and let users reset their profile.

## Limitations

- The session-level results come from simulated users. Real customers and devices need to be measured before the thresholds are trusted.
- Mouse movement alone is weak on real data.
- Mobile touch input isn't covered.
- The code has not had an independent security review, including attempts to replay or imitate a customer's behaviour. Real use also needs consent and a fairness check across ages, abilities and devices.

See [SECURITY.md](SECURITY.md), [docs/threat-model.md](docs/threat-model.md) and [docs/model-card.md](docs/model-card.md).

## License

MIT. See [LICENSE](LICENSE).
