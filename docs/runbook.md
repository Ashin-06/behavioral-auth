# Runbook

How to deploy, configure and operate the behavioural authentication service. Commands assume the
repository root.

## Deploy

```bash
docker build -t behavioral-auth:1.0.0 .
python -m behavauth.ops keygen          # one API key per client
docker run -d --name behavauth -p 8007:8007 -v behavauth-data:/data \
  -e BEHAVAUTH_KEYS_FILE=/run/secrets/behavauth-keys.json \
  behavioral-auth:1.0.0
curl -fsS http://127.0.0.1:8007/readyz
```

The image runs in production mode as a non-root user and keeps its SQLite database (profiles and
session logs) in the `/data` volume. It refuses to start, and logs why, when anything required is
missing. Terminate TLS in front of it.

Live session trust is held in the process that started the session. Run one replica, or route
every call for a session to the same replica (sticky by session id). Profiles and logs can live in
Postgres (`BEHAVAUTH_DATABASE_URL=postgresql://user:pass@host/db`) so replicas share them, and a
profile refits when another replica adds enrollment windows.

Without Docker: `pip install -r requirements.lock && pip install -e .`, then `behavauth serve`.

## Configure

| Variable | Required in production | Meaning |
|---|---|---|
| `BEHAVAUTH_ENV` | — | `development` (default) or `production` |
| `BEHAVAUTH_API_KEYS` / `BEHAVAUTH_KEYS_FILE` | yes | JSON `{"sha256:<hex>": {"user": "...", "role": "..."}}`. Roles: `bank_backend` (enroll, sessions, events, actions, user status), `analyst` (`/api/sessions`), `monitor` (`/metrics`), `admin` |
| `BEHAVAUTH_DATABASE_URL` | yes (or `BEHAVAUTH_DB`) | `sqlite:////data/behavauth.db` or `postgresql://...`; default in development: `data/behavauth.db` in the repository |
| `BEHAVAUTH_DB` | — | the older setting: a SQLite file path, used when `BEHAVAUTH_DATABASE_URL` is unset |
| `BEHAVAUTH_SESSION_IDLE_S` | — | drop live sessions idle for longer than this (default 7200) |
| `BEHAVAUTH_HOST`, `BEHAVAUTH_PORT` | — | default `127.0.0.1:8007`; any non-loopback address needs API keys |
| `BEHAVAUTH_RATE_LIMIT` | — | requests per minute per client (default 120); the capture script posts every 10–15 s per session |
| `BEHAVAUTH_MAX_BODY_BYTES` | — | default 2,500,000 |
| `BEHAVAUTH_CORS_ORIGINS` | — | comma-separated origins allowed to call from a browser; none by default |
| `BEHAVAUTH_LOG_LEVEL` | — | default `INFO` |
| `FORWARDED_ALLOW_IPS` | — | addresses of proxies whose `X-Forwarded-For` is trusted (uvicorn) |

The old `BEHAVAUTH_API_KEY` (one shared key) is replaced by the key list above.

The rate limit counts per API key, so a back end relaying many customers needs a limit sized for
all of them, or one key per front-end node.

## Watch

- `GET /healthz`: the process is up (used by the container health check).
- `GET /readyz`: database reachable; 503 otherwise.
- `GET /metrics` (role `monitor`): `http_requests_total`, `http_request_duration_seconds`,
  `errors_total`, `behavauth_decisions_total{decision="window_allow|window_step_up|window_block|action_allow|action_step_up|action_hold|action_deny"}`.
- Logs are one JSON object per line on stdout, each with a `request_id` that is also returned in
  the `X-Request-ID` response header. Event streams are never logged.

Suggested alerts: `/readyz` failing for 2 minutes; `errors_total{kind="unhandled"}` increasing;
5xx share above 1% for 10 minutes; the `action_deny` or `action_hold` share moving sharply (an
attack wave, or a front-end release that changed what the capture script sees).

## Rotate keys

Add the new hash to the key file, restart, give the client the new key, then remove the old hash
and restart again. Restarting drops live sessions: clients start new ones, and sensitive actions
step up until enough behaviour is seen.

## Retention and profile reset

Nothing is deleted automatically. Apply the bank's retention period and honour profile resets
with SQL against the database, for example:

```sql
DELETE FROM windows WHERE t < :cutoff_epoch_seconds;
DELETE FROM sessions WHERE started < :cutoff_epoch_seconds;
DELETE FROM enrollment WHERE "user" = :user_id;        -- a customer asks for their profile to be reset
```

## Back up and restore

SQLite (in the `/data` volume):

```bash
docker exec behavauth python -c "import sqlite3; s=sqlite3.connect('/data/behavauth.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker cp behavauth:/data/backup.db ./behavauth-$(date +%F).db
```

Restore: stop the container, copy the backup to `/data/behavauth.db` in the volume, start it and
check `/readyz`. Enrollment windows added after the backup are lost; those users re-enroll.

Postgres: `pg_dump` / `pg_restore` as usual. Migrations are applied automatically on start, or with
`python -m behavauth migrate`. Backups hold personal data: store them like the customer database.

## Incidents

1. **Fraud got through on a session the service allowed.** Find the session id in the bank's logs,
   read its timeline from `/api/sessions` (or the `windows` table), and check which signals were
   present. Add the pattern to the simulator and the threat rules, then re-run
   `python -m behavauth evaluate`.
2. **Many genuine customers stepped up or denied.** Compare by device, browser and front-end
   release; a changed capture script or a new device class shifts the features. Re-calibrate
   `STEP_UP_BELOW` / `END_BELOW` (`engine.py`) on recent genuine sessions.
3. **Leaked API key.** Remove its hash from the key file and restart. Look for enrollments made with
   it (poisoned profiles) and reset those users. Issue a new key.
4. **Database exposed.** Profiles are personal data: follow the bank's data-breach procedure (DPDP
   Act notification duties) and reset the affected profiles.
