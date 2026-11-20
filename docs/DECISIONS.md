# Design decisions

Non-obvious design decisions, with the alternatives considered and the reason for each choice.
The README's "Key design decisions" table is drawn from this file.

Format: **Decision**, *Context*, **Alternatives**, **Why**, **Milestone**.

---

## D-001 Pin Node 24 LTS (npm 11) for the frontend toolchain

- **Context:** With Node 22.13 / npm 10.9.2, `npm install` crashed with
  `TypeError: Cannot read properties of null (reading 'edgesOut')` in arborist's `#loadPeerSet`.
  The cause: `vitest@4.1.12` declares an optional peer `@vitest/browser-webdriverio@^4.1.11`, but
  4.1.12 of that package was never published. npm 10.9's arborist crashes on that conflict
  instead of reporting `ERESOLVE`.
- **Alternatives:** stay on Vitest 3.2 (its tree carries a critical `tinypool` advisory and a
  moderate `@vitest/mocker` advisory); `--legacy-peer-deps` via `.npmrc` (hides real peer
  problems for every package); pin an older Vitest 4.1.x (still inside the advisory range).
- **Why:** Node 24 is the current LTS and bundles npm 11, which resolves the tree correctly.
  This keeps `vitest ~4.1.12` (outside the advisory range) and gives a clean `npm audit`.
- **How it is enforced:** `frontend/package.json` `engines.node` is `>=24 <25`;
  `frontend/.nvmrc` is `24`. The frontend Dockerfile (M5) uses a `node:24` build image and the
  CI workflow (M5) uses `actions/setup-node` with `node-version: 24`.
- **Milestone:** M0

## D-002 Approve esbuild's install script explicitly

- **Context:** npm 11 does not run dependency install scripts unless a package is approved under
  `allowScripts` in `package.json`. esbuild (pulled in by Vite) has a postinstall that verifies
  its platform binary.
- **Alternatives:** leave it unapproved (the build still works because the binary comes from an
  optional dependency, but every install prints a warning); allow all scripts globally.
- **Why:** an explicit, version-pinned allow-list (`"esbuild@0.28.2": true`) keeps installs
  deterministic and quiet while still blocking scripts from any other package. Revisit the entry
  when esbuild is upgraded.
- **Milestone:** M0

## D-003 Frontend toolchain versions: newest set known to work together, not newest available

- **Context:** At build time the newest releases were Vite 8, TypeScript 7 (native port) and
  ESLint 10.
- **Choice:** React 18.3.1 (per spec), Vite 7.3, `@vitejs/plugin-react` 5.2, TypeScript 5.9,
  ESLint 9.39 + typescript-eslint 8, Vitest 4.1.12, jsdom 26.
- **Why:** the brief requires that every artifact runs without errors. typescript-eslint
  officially supports TypeScript 5.x, and this set of major versions is mutually compatible.
  The newest majors add upgrade risk without adding anything this project needs. Versions use
  `~` ranges with a committed `package-lock.json`, so `npm ci` reproduces the exact tree.
- **Milestone:** M0

## D-004 Vite app scaffolded by hand rather than `npm create vite`

- **Why:** the current template targets React 19 and the newest toolchain. The spec requires
  React 18, so writing the small set of config files by hand avoids then downgrading every
  generated dependency.
- **Milestone:** M0

## D-005 `/api/health` always returns HTTP 200 with `status: ok | degraded`

- **Context:** on first start-up Ollama may still be booting or downloading the model, which can
  take many minutes.
- **Alternatives:** return 503 when the model is not ready.
- **Why:** the frontend polls this endpoint to show a "model downloading / not ready" banner, and
  the Docker healthcheck only needs to know that the backend process is up. A 200 with
  `model_ready: false` means "backend alive, model not ready", which is different from "backend
  unreachable". In mock mode `model_ready` is always true. The check calls Ollama's
  `GET /api/tags` with a 3-second timeout. It moves behind the LLM provider interface in M2.
- **Milestone:** M0

## D-006 API docs served under `/api/docs`

- **Why:** the spec prefixes every route with `/api`, and in production nginx proxies only `/api`
  to the backend. Serving `/docs` and `/openapi.json` under `/api` means the interactive docs
  work both through the frontend origin (port 8080) and directly on the backend.
- **Milestone:** M0

## D-007 JSON logging with the standard library only

- **Alternatives:** `python-json-logger`, `structlog`.
- **Why:** a ~30-line `logging.Formatter` covers the need (one JSON object per line plus
  `job_id` / `document_id` / `stage` / `duration_ms` context fields passed through `extra`)
  without adding a dependency outside the approved stack. Uvicorn's loggers are routed through
  the same handler so all output is JSON.
- **Milestone:** M0

## D-008 App factory (`create_app(settings)`) with per-app settings

- **Why:** tests build isolated app instances with their own settings (mock provider, temp data
  dir) without editing environment variables or global caches. Production uses the module-level
  `app = create_app()`, which reads settings from the environment through `pydantic-settings`.
- **Milestone:** M0

## D-009 Exact pins for Python dependencies; tool config in `backend/pyproject.toml`

- **Why:** `requirements.txt` / `requirements-dev.txt` pin exact versions for reproducible Docker
  and CI builds. `pyproject.toml` holds only ruff and pytest settings; it is not used for
  packaging. Ruff enables the `S` (bandit) security rules alongside the usual style and bug rules.
  `pydantic-settings` is used for `config.py`, as named in the spec's layout.
- **Milestone:** M0

## D-010 ESLint rule bans `dangerouslySetInnerHTML`

- **Why:** the spec requires all model output to be rendered as plain text (prompt-injection
  defence #5). A lint error enforces this in CI instead of relying on code review.
- **Milestone:** M0

## D-011 LF line endings forced for shell scripts and Docker files

- **Why:** the author develops on Windows with `core.autocrlf`. A CRLF `.sh` file or `Dockerfile`
  fails inside Linux containers and CI, so `.gitattributes` forces `eol=lf` for `*.sh`,
  `Dockerfile` and `*.conf`.
- **Milestone:** M0

---

## Pending decisions (to record when made)

- Final Ollama model tag (verify `qwen3-vl:4b-instruct` exists in M2).
- Whole-page rendering for visual analysis (M1/M2), as per spec section 6.
- Triage rubric (M7), as per spec section 8.
