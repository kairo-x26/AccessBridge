# Developer guide

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.8+ | Python 3.13 environment and dependencies |
| Node.js | 24+ | Frontend |
| pnpm | 10+ | Frontend dependencies |
| Docker (optional) | | PostgreSQL and the compose stack |

No database server is needed for development: the backend uses SQLite under `backend/var/`.

## First run

```bash
# Backend
cd backend
uv sync --all-extras
uv run python -m app.seed --reset        # synthetic clinic network
uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
uv run python -m app.workers.run         # second terminal: background jobs and sweeps

# Frontend
cd frontend
pnpm install
echo 'BACKEND_URL=http://127.0.0.1:8000' > .env.local
echo 'NEXT_PUBLIC_DEMO=1' >> .env.local
pnpm dev                                 # http://localhost:3000
```

Or start everything at once with `./demo/run_demo.sh`.

Sign in to organization `riverbend` with password `Demo-Password-2026`; accounts are
listed in the [demo guide](../demo/README.md).

## Repository map

```
backend/            FastAPI API, worker, domain logic, tests, migrations
  app/              see ARCHITECTURE.md for the module layout
  migrations/       Alembic (baseline generated from PostgreSQL)
  tests/            pytest: unit, API, workflow, acceptance; tests/perf for latency
frontend/           Next.js 16 app
  src/app/          routes: (app)/… authenticated pages, login, accept-invitation, api/ BFF
  src/components/   ui/ primitives, route/ route line and map, charts/, app/ shell
  src/lib/          api client, generated schema types, formatting, hooks
  tests/unit        Vitest + Testing Library + axe-core
  tests/e2e         Playwright against a production build and a seeded backend
demo/               run_demo.sh, scenario.py, sample data
docs/               guides (this file, architecture, user, admin, operations, …)
```

## Everyday commands

| Task | Command |
|---|---|
| Backend tests | `cd backend && uv run pytest` |
| Backend tests on PostgreSQL | `AB_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db uv run pytest` |
| Latency check (NFR p95) | `uv run pytest -m perf -s tests/perf` |
| Extraction evaluation | `uv run python -m app.evaluation.extraction` |
| Lint and types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` |
| New migration | `uv run alembic revision --autogenerate -m "describe change"` |
| Apply migrations | `uv run alembic upgrade head` |
| Frontend checks | `cd frontend && pnpm lint && pnpm typecheck && pnpm test` |
| End-to-end tests | `pnpm test:e2e` (starts its own servers on ports 8100 and 3100) |
| Regenerate API types | `pnpm gen:api` after changing backend request/response models |
| Refresh doc screenshots | demo running, then `pnpm screenshots` |

CI (`.github/workflows/ci.yml`) runs backend checks on SQLite and on PostgreSQL (including
the migration drift check), frontend checks, and the end-to-end suite.

## Conventions

**Backend**

* Domain rules live in `app/domain` as plain functions with no I/O. If a rule decides
  whether something is allowed, it belongs there and gets an exhaustive test.
* Every tenant-owned query uses `scoped()` / `get_scoped()` from `app/core/tenancy.py`.
  Never call `session.get()` on a tenant-owned model with an id from a request.
* Endpoints declare permissions with `require(Perm.X)`; add new permissions to
  `domain/rbac.py` and the matrix test.
* Mutations write an audit event with references, never values (`services/audit.py`). Use
  `record_detached` for denials, which must survive the request's rollback.
* Status changes go through `services/referrals.transition()` only.
* Anything retried must be idempotent. Pick a natural key (source reference, action key,
  event id) and enforce it with a unique constraint.
* User-facing error messages say what happened and what to do, in plain language, without
  exception class names.
* Line length 100; ruff and mypy must be clean.

**Frontend**

* Pages are thin server components that render a client component inside `<Suspense>`
  (Next 16 requires it for `useSearchParams`/`usePathname`).
* Data comes through `useApi()` (SWR) and the typed `api` client; no direct `fetch` to the
  backend.
* Use the design tokens and components in `src/components/ui`; see
  [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md). New screens must pass the axe scan in
  `tests/e2e/workflows.spec.ts` (add them to the list).
* Copy is sentence case, plain verbs and the user's vocabulary ("Send package", not
  "Execute transmission").

## Adding things

### A new agent tool

1. Define an argument model (subclass `Args`, `extra="forbid"`) and a handler in
   `app/agents/tools.py`. The handler receives a `ToolContext` with the action's
   idempotency key; external side effects must use it.
2. Register a `Tool` with its risk class (`external`), permission, allowed states and
   `always_requires_approval` if it changes state or leaves the system.
3. Add it to the right workflow in `WORKFLOW_TOOLS` (`app/agents/policy.py`).
4. Teach the planner when to propose it (`app/agents/planner.py`).
5. Add tests: policy decisions, an adversarial proposal, idempotent re-execution, and the
   end-to-end flow.
6. Add a label in `frontend/src/lib/format.ts` (`TOOL_LABEL`) and, if it moves the referral,
   in `TOOL_TARGET` (`RouteMap.tsx`).

### A new specialty

Add it to `SUPPORTED_SPECIALTIES` (`services/referrals.py`), give it checklist extras in
`domain/checklists.py`, keywords in `integrations/fhir.py` (`_SPECIALTY_KEYWORDS`), and a
label in `SPECIALTY_LABEL` on the frontend.

### A new extracted field

Add it to `FIELDS` (and `CRITICAL_FIELDS` if a person must confirm it) in
`domain/checklists.py`, add label patterns and a format check in
`services/document_ai.py`, extend the evaluation corpus, and re-run the evaluation.

### A new message template type

Add the key and starting wording in `domain/templates.py`, a literal to `SendMessageArgs`,
planner rules for when to propose it, and labels in the frontend.

## Enabling the model provider (development)

```bash
export AB_LLM_PROVIDER=anthropic
export AB_ANTHROPIC_API_KEY=…            # or sign in with the ant CLI
export AB_LLM_MODEL=claude-opus-5-5      # default
```

The provider uses JSON-schema constrained output, server-side fallback on refusals, adaptive
thinking with `AB_LLM_EFFORT` (default `medium`), and is metered per call in `llm_usage`.
Tests never call it; they inject a `FakeProvider` via `gateway.set_provider()`. Use only
synthetic data unless a business associate agreement is in place (see
[SAFETY_AND_COMPLIANCE.md](SAFETY_AND_COMPLIANCE.md)).

## Troubleshooting

| Problem | Fix |
|---|---|
| `no such column` after pulling | Reseed: `uv run python -m app.seed --reset` (dev SQLite) or `alembic upgrade head` |
| 500 on every page, backend log shows a `TypeError` | The backend isn't running with `--reload`; restart it |
| UI types out of date | `pnpm gen:api` |
| e2e: port already used | Another app holds 3100/8100; change ports in `playwright.config.ts` |
| Agent proposals never run | The worker isn't running (`uv run python -m app.workers.run`) |
