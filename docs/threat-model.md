# Threat model

What the behavioural authentication service protects, from whom, and what is still open.
Written for the 1.0.0 code; it has not been reviewed by anyone independent.

## What it protects

| Asset | Where it lives |
|---|---|
| Sensitive actions in a banking session (transfers, new payees, phone changes) | gated by `/api/session/{id}/action` |
| Behavioural profiles: feature vectors of each customer's typing and pointer habits (personal data, biometric in many places) | `enrollment` table |
| Session logs: trust, match, decisions and reasons per 15-second window | `sessions` and `windows` tables |
| Live session trust and flags | memory of the process that started the session |
| Service API keys | callers hold the key; the service holds only SHA-256 hashes |

The capture script records timing and movement only, with key classes instead of characters, so
no password, account number or message text is collected or stored.

## Trust boundaries

```
customer browser (capture.js) ──► bank's web back end ──(TLS at your ingress)──► behaviour service ──► database
```

1. **Browser → bank back end.** Events are produced on a device the attacker may control (a bot,
   a remote-access tool, malware). Anything in them can be forged.
2. **Bank back end → service.** Authenticated by API key. The back end decides which user a
   session belongs to; the service trusts that.
3. **Service → database.** Profiles and logs are personal data; treat dumps and backups like the
   customer database.

## Threats and what stops them

| Threat | Mitigation | Residual risk |
|---|---|---|
| Impostor with the right password | Per-user scaled-Manhattan profile, trust that accumulates across windows | On simulated users 10% of impostors were still allowed a transfer; on real typists window EER is 10.3% (key classes), and mouse alone is weak (Balabit AUC 0.72) |
| Bot or scripted input | Profile-free rules (hold-time variance, rhythm regularity, straight paths, machine-exact clicks) | A bot that replays recorded human timing is not covered by these rules |
| Remote-access takeover (AnyDesk-style) | Frame-burst pointer timing, cursor teleports, injected key timing | Tools that smooth their input, or attacks that need no pointer movement |
| Coached victim | Pasted payee details, long silences before typing fields → hold with a scam warning | A victim who types everything themselves at a normal pace |
| Forged events that imitate the owner | — | Anyone who records a customer's behaviour (malware on the device) can try to replay it; the service cannot tell, since it only sees what the back end relays |
| Session trust lost or reset | Trust is per process; an unknown session returns 404 and a new session starts with no history, so sensitive actions step up | Run one replica or sticky sessions; across replicas a session is unknown |
| Stale profile on another replica | Profiles refit when the enrollment count changes | — |
| Poisoned enrollment (an attacker enrolls their own behaviour) | Enrollment calls need the `bank_backend` role | Passive enrollment from early sessions trusts that those sessions were the owner; enroll only after a strong login |
| Analyst feed exposure | `/api/sessions` needs the `analyst` role, separate from scoring | It lists user ids and decision timelines for recent sessions |
| Stolen API key | Per-client keys, roles, rate limit per key | Works until removed from the key list and the service restarts |
| Oversized or flooding requests | 2.5 MB body cap, 20,000 events per batch, per-client token bucket | Per process; put a shared limiter at the ingress |
| Errors leak data | Validation errors carry no input; unhandled errors return only a request ID | — |
| Misconfigured production start | `BEHAVAUTH_ENV=production` refuses to start without hashed keys and a database; no public bind without keys; `seed` refused | — |

## Not covered

- TLS. Terminate it at your ingress; the service speaks plain HTTP.
- Device integrity: malware that records and replays behaviour, or drives the browser itself.
- Encryption of profiles at rest beyond what the database or disk provides.
- Retention: nothing is deleted automatically. The runbook has the SQL to apply a retention
  period; the bank must choose one under the DPDP Act.
