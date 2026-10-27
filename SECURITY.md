# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately, through GitHub's private vulnerability
reporting on this repository (Security → Report a vulnerability) or by contacting the
maintainer, [@Ashin-06](https://github.com/Ashin-06), directly. Do not open a public issue.

Include what you found, how to reproduce it and what an attacker could do with it. You should
get an acknowledgement within 5 working days. Please give us 90 days to fix an issue before
disclosing it, and don't test against anyone else's deployment.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | yes |
| < 1.0 | no (prototype releases) |

## Scope

In scope: the behavioural authentication service and its HTTP API, the feature extraction,
identity model, threat rules and gating logic, the browser capture script (`web/capture.js`),
the demo pages, the container image and the CI configuration in this repository.

Out of scope: your reverse proxy or TLS setup, the bank's login and step-up systems, and
findings that need an already-compromised host or a leaked API key. An impostor, bot or remote
operator that passes is a detection limit rather than a vulnerability; the README lists the
known ones. Reports of new evasions are still welcome through the same channel.

This project has **not** had an independent security review or penetration test.
