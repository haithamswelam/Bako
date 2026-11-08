BAKO BATCH 5: traces + SRE assistant (first step)
=================================================
Replaces batch 4. Everything from batch 4 is inside.

WHAT IS NEW
1. Observability > Traces tab (real now): where the time of a request goes (database, password check, outside calls, other code),
   queries by total time (shape only: "SELECT users"), one request step by step, history per day.
2. The Overview "How it travelled" card fills the Database box with the measured share once traces were read.
3. SRE mode for Bako: every "Ask Bako" on the Observability page now goes to an SRE assistant with its own read-only tools
   (endpoint_stats, neighbours, traces, pods, database, find_code) and an EVIDENCE PACK inside the question (numbers collected by code first:
   this request vs its endpoint, what happened around it, trace split, pods, database, and what is NOT measured).
   The lab chat keeps its old tools. SRE mode can only read: it cannot propose or change anything.
4. "How Bako got to this answer" under every Observability answer: the evidence it was given (measured / not measured), every tool it called with
   its result, model, tokens, cost. Each case is also saved in agent/env/reports/sre-cases.jsonl (kept for testing Bako on past cases later).
5. The "Bako and AI" flow page has a new lane "SRE tools".
6. STOP stage "Save app facts" now also saves the per-endpoint time split (numbers only) when traces are running.

INSTALL (in this order)
A. Copy the zip contents over your repo root (it keeps the folders): agent/env/*.py (10 files, 2 new: obs_traces.py, sre.py),
   K8s/tracing.yaml (new), patch_tracing.py.
B. From the repo root:   python patch_tracing.py
   It adds 4 OTEL_ settings to K8s/backend-deployment.yaml and wraps the password check/hash in named spans in app/security.py,
   plus tests/test_security_spans.py. Safe to run twice; makes .bak files. Read its messages: if it says "nothing changed", send me that file.
C. Commit and push (git add -A). CI builds the image, the bot opens the PR, you merge. Argo CD then starts the trace receiver (jaeger) and the new backend.
   If you only want to see the tab first: copy K8s/tracing.yaml alone; the backend already has the tracing code, it just needs the OTEL_ settings (step B).
D. Restart the dashboard.
E. With the lab up: use the app for a minute (log in, add a record), then Observability > Traces > "Read the traces now".

WHAT TO CHECK
- Traces tab: does POST /login show a big "password check" part and a small "database" part? That would confirm the 600 ms is the password hashing.
- Overview: pick a request > "Ask Bako to troubleshoot this" > open "How Bako got to this answer". Does the evidence list make sense? Is anything marked not measured that should not be?
- The old "Not measured yet" text in the Database box should now say how many ms of a typical request the database takes.

NOT TESTED / CAVEATS
- Tested here on a fake cluster and a fake trace receiver; the model call was tested with a fake model client, not your OpenAI key.
- tracing.yaml uses image jaegertracing/all-in-one:1.62.0 from Docker Hub; if your nodes cannot pull it, tell me the error.
- The receiver keeps traces in memory (newest 5000); they vanish at STOP, which is why STOP saves the numbers first.
- agent.py, flow_tab.py, bako_chat.py are my last delivered versions plus these changes. If you edited any of them, send me yours and I merge.
- patch_tracing.py cannot see your real K8s/backend-deployment.yaml; it handles "env: exists" and "no env yet". Anything else it reports and leaves untouched.
- Hardcoded JWT SECRET_KEY in app/security.py is NOT touched (noted earlier).
- Not built yet (agreed order): change proposals + approval + PR with a required test, the after-deploy before/after check, replay of saved cases.
