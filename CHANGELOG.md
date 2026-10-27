# Changelog

All notable changes to this project. Versions follow [semantic versioning](https://semver.org/).

## 1.0.0 — 2026-10-27

### Added
- `pyproject.toml` with a `behavauth` console command, and pinned `requirements.lock` /
  `requirements-dev.lock` (generated with `uv pip compile --universal`). scikit-learn and
  matplotlib moved to an `evaluate` extra; the service itself doesn't need them.
- Container image: slim Python 3.12 base, non-root user, health check on `/healthz`.
- CI on every push: ruff, bandit, pip-audit, pytest with a coverage report.
- Settings from `BEHAVAUTH_*` environment variables, checked at startup. `BEHAVAUTH_ENV=production`
  refuses to start without hashed API keys and a database URL. `seed` refuses to run in production.
- Roles on API keys: `bank_backend` scores sessions and enrolls users, `analyst` reads the session
  feed, `monitor` scrapes metrics, `admin` does all three. Keys can be stored as `sha256:<hex>`;
  `python -m behavauth.ops keygen` makes new ones.
- Per-client rate limit, request body cap, security headers, CORS only for listed origins.
- JSON logs with request IDs; `/healthz`, `/readyz` and Prometheus `/metrics` with a
  `behavauth_decisions_total` counter.
- Postgres support through `BEHAVAUTH_DATABASE_URL`, numbered SQL migrations
  (`python -m behavauth migrate`).
- `SECURITY.md`, `docs/threat-model.md`, `docs/runbook.md`, `docs/model-card.md`.

### Changed
- The store uses SQLAlchemy instead of `sqlite3` directly. `BEHAVAUTH_DB` still names a SQLite file
  when `BEHAVAUTH_DATABASE_URL` is unset, and a database made by earlier versions upgrades in place.
- A cached profile is refitted when the user's enrollment count changes, so enrollment on one
  replica reaches the others.
- The single `BEHAVAUTH_API_KEY` is replaced by `BEHAVAUTH_API_KEYS` / `BEHAVAUTH_KEYS_FILE`
  (several keys, hashed, with roles); `/api/sessions` now needs the `analyst` role.
- Action amounts must be finite and non-negative.
- The demo pages send an API key when the service has keys.
- Without API keys the service refuses to listen on anything but loopback.

### Unchanged
- Features, identity model, threat rules and gating. `python -m behavauth evaluate` was re-run with
  the locked dependencies and gives output identical to `results/results.json`. The CMU and
  Balabit numbers in `results/real_data.json` were not re-run (the datasets are not on this
  machine) and are unchanged.
