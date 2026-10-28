# Evaluation

## Simulated users

`python -m behavauth evaluate`: 30 simulated users, each with their own typing and mouse habits, enrolled from three one-minute sessions.

![results](../results/summary.png)

| Measure | Result |
|---|---|
| Identity from 15 s of behaviour (equal error rate) | keystroke 18.3%, mouse 14.1%, combined 10.7% |
| Genuine users, ₹20,000 transfer after 90 s | 90% allowed, 10% asked to step up, 0% denied |
| Impostor with the right password | 77% denied, 13% step-up, 10% allowed; median 15 s to the first flag |
| Bot sessions | 100% denied |
| Remote-access takeover | 100% denied |
| Coached victim | 97% stopped (50% held with a scam warning, 40% denied, 7% step-up) |

One 15-second window is weak evidence, which is why the error rate per window is around 11%. Trust builds up over several windows, which is how the session-level results get much higher. The simulator models real effects such as minimum-jerk pointer motion, device sampling rates and remote-desktop frame pacing, but real people are messier.

## Real people

`python -m behavauth realdata` scores the same identity model, with no impostor data at enrolment, on two public datasets. Results go to `results/real_data.json`.

| Dataset | What is scored | Result |
|---|---|---|
| [CMU keystroke benchmark](https://www.cs.cmu.edu/~keystroke/) (51 people, 400 typings each) | per-key timings, the paper's protocol | 8.9% EER (paper: 9.6%) |
| same | the key-class features this service actually stores, 5 typings per window | 10.3% EER |
| [Balabit mouse challenge](https://github.com/balabit/Mouse-Dynamics-Challenge) (10 users, 816 test sessions, 405 by intruders) | is this session the account owner? mouse only | AUC 0.72, 32.7% EER |

The keystroke model holds up on real typists, and storing key classes instead of the actual keys costs little. Mouse movement alone is weak: the Balabit sessions are short, recorded over remote desktop, and the model never sees intruder data. The mouse signal should only support typing and the threat rules, never decide identity on its own.
