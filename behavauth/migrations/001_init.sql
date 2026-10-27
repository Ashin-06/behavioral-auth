-- The tables the service always had. IF NOT EXISTS lets a database file made before
-- migrations existed (BEHAVAUTH_DB) upgrade in place. "user" is quoted because it is a
-- reserved word in Postgres. Times are epoch seconds.
CREATE TABLE IF NOT EXISTS enrollment (
    "user" TEXT NOT NULL,
    created DOUBLE PRECISION NOT NULL,
    features TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS enrollment_user ON enrollment ("user");

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    "user" TEXT,
    started DOUBLE PRECISION,
    last_trust DOUBLE PRECISION,
    last_action TEXT
);
CREATE INDEX IF NOT EXISTS sessions_started ON sessions (started);

-- One row per scored window of behaviour; reasons is a JSON list.
CREATE TABLE IF NOT EXISTS windows (
    session_id TEXT,
    t DOUBLE PRECISION,
    trust DOUBLE PRECISION,
    match DOUBLE PRECISION,
    action TEXT,
    reasons TEXT
);
CREATE INDEX IF NOT EXISTS windows_session ON windows (session_id, t);
