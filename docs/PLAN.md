# AccessBridge AI — Build Plan

This plan turns `AccessBridge_AI_Project_Requirements.md` (the spec) into a working
system, from an empty repository to a demonstrable full version. Every phase ends with
automated tests passing and a set of commits. Requirement IDs (FR-xx, NFR) refer to
the spec.

## Guiding decisions

| Decision | Choice | Why |
|---|---|---|
| Shape | Modular monolith + async worker (spec §10) | Simple to operate; clear module seams |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic | Spec stack; typed contracts |
| Database | PostgreSQL in deployment; SQLite for local dev and tests | Same SQLAlchemy models; no daemon needed to develop |
| Durable work | Database-backed job queue (lease, retry with backoff, dead-letter, idempotency keys) behind a `WorkflowEngine` interface | Meets NFR reliability without running Temporal for the MVP; interface allows a Temporal adapter later |
| AI | `LLMGateway` with a deterministic local provider (default, offline, used by tests) and an Anthropic provider (optional, env-configured) | Tests reproducible; no PHI leaves the box unless configured |
| AI authority | AI proposes; a deterministic policy engine and state machine decide | Spec §10 decisions 1–3 |
| Frontend | Next.js (App Router) + TypeScript, hand-built design system on CSS custom properties | Spec stack; WCAG 2.2 AA control |
| Auth | Local password + TOTP MFA, JWT access tokens, OIDC-ready seam | FR-01 without an external IdP in dev |
| Integrations | Simulated FHIR R4 adapter (ServiceRequest/Task), simulated secure exchange, simulated SMS with HMAC-signed webhooks | Recommended first milestone (spec §20) |

## Repository layout

```
backend/          FastAPI app, worker, domain modules, tests
  app/core        config, db, security, logging, errors
  app/models      SQLAlchemy entities (spec §8)
  app/domain      state machine, policy engine, checklists (pure logic)
  app/services    intake, documents, agents, messaging, outcomes, rag, reports
  app/integrations  FHIR, exchange, messaging adapters (simulated + interface)
  app/api         versioned routers (/v1)
  app/workers     job queue + handlers
frontend/         Next.js app + design system
demo/             synthetic data, scenario runner, demo guide
docs/             plan, architecture, guides, ADRs
```

## Design system (frontend)

- **Signature element:** the referral *route line* — the state machine drawn like a
  transit line. Mini route in each queue row; full route with evidence at every stop
  on the referral page.
- **Encoding rule:** AI-proposed content is violet with a dashed outline;
  human-verified or evidence-backed content is solid. Unverified never looks verified.
- **Palette:** paper `#F5F7F6`, ink `#18262F`, bridge teal `#0E6B66`, agent violet
  `#5847B0`, exception amber `#8F5600`, verified green `#2C7A3A`, alert red `#B3261E`;
  dark-mode equivalents defined as tokens.
- **Type:** Atkinson Hyperlegible Next (legibility-first, matches the WCAG goal),
  one family, weight contrast, tabular numerals, sentence-case labels.
- **Layout:** narrow left rail → work area. Queue = dense table. Referral detail =
  route (left) · documents and evidence-linked fields (center) · agent proposals and
  approvals (right).

## Phases

Each phase: build → test (unit + API + where relevant UI/e2e) → fix → commit.

### Phase 0 — Foundations (Oct 2025)
Repo scaffolding, tooling (ruff, mypy, pytest), config, DB session, Alembic, health
endpoint, structured logging with PHI redaction, CI workflow.

### Phase 1 — Identity, tenancy, audit (Oct–Nov 2025) · FR-01, FR-02, FR-18
Organizations, users, invitations, password hashing, TOTP MFA, JWT sessions, RBAC
permission matrix, tenant-scoped repositories, audit event log + data-access audit.
Tests: cross-tenant access attempts are all rejected; role matrix.

### Phase 2 — Referral core (Nov 2025–Jan 2026) · FR-03, FR-04, FR-08, FR-19
Referral state machine (spec §6) as pure code; patient references, providers,
referrals, documents (checksummed storage), status events with evidence; intake via
simulated FHIR `ServiceRequest` bundles and CSV; idempotent import (duplicate
markers); task queue (owner, due, priority, escalation); reconciliation of inbound
FHIR `Task` updates. Tests: exhaustive transition table, duplicate import, idempotency.

### Phase 3 — Document intelligence & validation (Jan–Feb 2026) · FR-05, FR-06, FR-07, FR-20
Text extraction (text, PDF), document classification, typed field extraction with
source spans + confidence, "no fabrication" validator (value must appear in source),
specialty checklists (configurable), missing-info tasks, reviewer correction and
package approval. Tests: precision/recall evaluation harness on synthetic corpus.

### Phase 4 — Agents, tools, approvals, durable jobs (Feb–Mar 2026) · FR-09, FR-10
Job queue (lease/retry/dead-letter), LLM gateway (deterministic + Anthropic) with PHI
minimization and usage metering/caps, tool registry with typed schemas, policy engine
(permission + approval requirements), agent runs/actions/approvals, approval decision
API, adapters for transmission with idempotency. Tests: adversarial prompt-injection
documents cannot widen tool scope; zero unauthorized external actions; retries do not
duplicate transmission.

### Phase 5 — Communication & outcomes (Mar–Apr 2026) · FR-11, FR-12, FR-13, FR-15
Message templates (en/es, reviewed flag), consent and contact preferences, opt-out
enforcement, simulated SMS provider with signed webhooks, delivery tracking, response
classification (confirmed / needs assistance / declined / unknown, with medical or
urgent escalation), follow-up workflow B, completion workflow C requiring evidence.

### Phase 6 — Clinic operations dashboard (Apr–Jun 2026) · UI for FR-01…FR-17
Design system tokens + components, auth + MFA screens, referral queue with route
lines and filters, referral detail (route, documents, evidence-linked fields, review
and approve), approvals inbox, tasks, communications, audit viewer. Tests: Vitest
component tests, axe accessibility checks, Playwright e2e of workflow A.

### Phase 7 — Policy assistant, reports, configuration (Jun–Jul 2026) · FR-14, FR-17, FR-21, FR-20
Policy document ingestion, chunking, lexical retrieval with tenant filtering, cited
answers or explicit "not found", retrieved-text injection guard; operational metrics
(age, status distribution, exceptions, ownership), CSV export of aggregates; checklist
and workflow rule admin UI.

### Phase 8 — Hardening (Jul 2026) · NFRs
Metrics endpoint, request tracing IDs, rate limiting, security headers, retention
job, performance check of p95 reads, extraction evaluation report, acceptance-criteria
test suite (spec §14), Docker images and docker-compose (Postgres).

### Phase 9 — Demo and guides (Aug 2026)
Synthetic clinic network seed, scenario runner covering workflows A/B/C, demo
walkthrough, user guide, admin guide, developer guide, API reference, safety/scope
notes.

## Out of scope (stated, not hidden)
Live PHI, real EHR vendor connections, real SMS delivery, voice automation (FR-16),
insurance eligibility (FR-22), Terraform deployment to AWS. Interfaces exist where a
later adapter would plug in.
