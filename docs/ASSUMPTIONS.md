# Assumptions

Assumptions made while building, grouped by area. Code-level assumptions are marked
`# ASSUMPTION:` in the source and mirrored here.

## General

- A-001: The app runs for a single analyst on one machine. There is no authentication or
  multi-user isolation (out of scope for the brief).
- A-002: Sample documents and synthetic tickets are fictional or public. No real sensitive data
  is committed to the repo.

## Backend

- A-101: Python 3.12 is the target runtime for local development, Docker and CI.
- A-102: The default model tag `qwen3-vl:4b-instruct` is assumed to exist in the Ollama registry.
  It is verified in M2, and the final choice goes in DECISIONS.md.
  (`backend/app/config.py`, `# ASSUMPTION:`)
- A-103: "Model ready" means Ollama's `GET /api/tags` lists the configured model. It does not
  check that the model loads into memory; the first real call may still be slow while it loads.
- A-104: Logs contain metadata only (IDs, stages, durations, error codes). Document content and
  model outputs are never logged, which is a deliberate choice for sensitive data. The trade-off
  is that debugging relies on stored results rather than log lines.

## Frontend

- A-201: Node 24 LTS (npm 11) is the frontend toolchain (see DECISIONS D-001).
- A-202: In development the backend runs on `localhost:8000`. Vite proxies `/api` there,
  which can be overridden with `VITE_API_PROXY_TARGET`.
- A-203: The analyst uses a current evergreen browser (ES2022 support).

## CI / Docker

- _(added in M5)_
