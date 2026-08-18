# Operations runbook

How to deploy, configure, monitor and recover AccessBridge. Targets below are the proposed
engineering targets from the requirements (§5), not achieved service levels.

## Components

| Process | Command | Scale | Notes |
|---|---|---|---|
| Web (Next.js) | `node server.js` (standalone image) | 2+ behind TLS | Holds no state; the only public entry point |
| API (FastAPI) | `uvicorn app.main:app --workers 2 --proxy-headers` | 2+ | Private network only; reachable from web |
| Worker | `python -m app.workers.run` | 1–N | Claims are atomic; run several for throughput and failover |
| Migrate | `alembic upgrade head` | one-shot per release | Runs before API and worker start |
| PostgreSQL | managed (RDS) | primary + standby | Source of truth, including the job queue |
| Document store | encrypted volume (S3 + KMS in AWS) | | Content-addressed, encrypted per file |

## Deploying with Docker Compose

```bash
cp .env.example .env        # fill every value (see below)
docker compose up --build -d
docker compose logs -f migrate api worker
```

For a demo with synthetic data, set `AB_ENVIRONMENT=development` and `NEXT_PUBLIC_DEMO=1` in
`.env`, then `docker compose run --rm api python -m app.seed`. Never seed a production database.

Production deployments (AWS ECS/Fargate, RDS, S3, KMS per the requirements) map one-to-one:
web and API as services, the worker as a service without a load balancer, and migrate as a
one-off task in the release pipeline.

## Configuration reference

All backend settings are environment variables prefixed `AB_`.

| Variable | Default | Production |
|---|---|---|
| `AB_ENVIRONMENT` | `development` | `production`: hides `/docs`, removes simulators, adds HSTS, refuses dev secrets and SQLite |
| `AB_DATABASE_URL` | SQLite in `backend/var` | `postgresql+psycopg://…` |
| `AB_STORAGE_DIR` | `backend/var/documents` | Encrypted persistent volume |
| `AB_JWT_SECRET` | dev value | 32+ random characters, from the secret manager |
| `AB_FIELD_ENCRYPTION_KEY` | derived from JWT secret | Fernet key from KMS-backed secret; **losing it makes encrypted fields unreadable** |
| `AB_ACCESS_TOKEN_MINUTES` | 30 | Session length |
| `AB_REQUIRE_MFA` | false | Platform-wide override; organizations can also require it |
| `AB_MESSAGING_WEBHOOK_SECRET` | dev value | Provider's signing secret |
| `AB_METRICS_TOKEN` | unset | Required in production to expose `/metrics` |
| `AB_TRUST_PROXY` | false | `true` only when the API is reachable solely through the web tier |
| `AB_CORS_ORIGINS` | `["http://localhost:3000"]` | The web origin |
| `AB_LLM_PROVIDER` | `deterministic` | `anthropic` only with a BAA (see safety doc) |
| `AB_ANTHROPIC_API_KEY`, `AB_LLM_MODEL`, `AB_LLM_EFFORT` | –, `claude-opus-5-5`, `medium` | Model access |
| `AB_LLM_MAX_TOKENS_PER_RUN` | 20000 | Per-run model budget |
| `AB_AGENT_MAX_TOOL_CALLS`, `AB_AGENT_MAX_EXTERNAL_ACTIONS` | 8, 1 | Per-run agent caps |
| `AB_FOLLOW_UP_AFTER_DAYS` | 5 | Workflow B trigger |
| `AB_JOB_MAX_ATTEMPTS`, `AB_JOB_LEASE_SECONDS` | 5, 60 | Retry and lease behaviour |

Web tier: `BACKEND_URL` (API base URL), `NEXT_PUBLIC_DEMO` (build-time; shows demo hints).

### Secrets rotation

* **JWT secret:** rotating signs everyone out. Rotate during a quiet window.
* **Field encryption key:** don't replace it in place. Re-encryption needs a migration that
  reads with the old key and writes with the new one. Back the key up with the database
  backup.
* **Webhook secret:** coordinate with the messaging provider; requests signed with the old
  secret fail closed (401).

## Monitoring

`GET /metrics` (Prometheus text, bearer `AB_METRICS_TOKEN`) exposes:

* `accessbridge_http_requests_total{method,route,status}` and
  `accessbridge_http_request_seconds` (histogram, by route template)
* `accessbridge_jobs{status}`: queued, running, succeeded, dead
* `accessbridge_referrals{status}`: aggregate counts only
* `accessbridge_agent_actions{decision}`: auto, approval_required, denied

Logs are JSON on stdout with `request_id`, and PHI patterns (SSN, phone, email, dates, MRN)
are redacted before writing. Every response carries `x-request-id` and `server-timing`.

Suggested alerts:

| Alert | Condition | Response |
|---|---|---|
| API latency | p95 of `/v1/*` reads > 500 ms for 10 min | Check database load and slow queries |
| Dead jobs | `accessbridge_jobs{status="dead"}` increases | See dead-letter handling below |
| Queue backlog | `queued` > 200 for 15 min | Add workers; check for a stuck lease |
| Auth failures | 401/429 on `/v1/auth/login` spike | Possible credential stuffing; review the audit log |
| Webhook rejects | 401 on `/v1/webhooks/messaging` | Secret mismatch or forged traffic |
| Health | `/health` failing | Database connectivity |

## Background jobs

The worker runs due jobs and schedules sweeps:

| Sweep | Cadence | Does |
|---|---|---|
| `sweep.escalation` | every minute | Raises overdue task priority (at most once a day per task) |
| `sweep.follow_up` | hourly | Starts follow-up agent runs for submitted, acknowledged and scheduled referrals |
| `sweep.retention` | daily | Purges working data of closed referrals past retention (legal holds excepted) |

Each sweep runs once per period across all workers (idempotency key per time bucket).

### Dead-letter handling

A job that fails `AB_JOB_MAX_ATTEMPTS` times (exponential backoff from 5 s, capped at 1 h)
becomes `dead`. Registered compensation runs: a failed transmission moves the referral to
Exception with a task. Otherwise a generic "Automated step failed" task is created. Admins
list failed jobs with `GET /v1/ops/jobs?status=dead` and retry with
`POST /v1/ops/jobs/{id}/retry` after fixing the cause. Approved actions re-check referral
state before running, so retrying a stale job is safe.

## Backups and recovery

Proposed objectives: **RPO 1 hour, RTO 4 hours**.

* PostgreSQL: continuous archiving / point-in-time recovery (RDS automated backups with
  5-minute log shipping) plus daily snapshots retained per policy.
* Document store: versioned bucket (or volume snapshots) on the same schedule.
* Field encryption key: in the secret manager, with its own recovery procedure.
* **Test restores quarterly:** restore into an isolated environment, run
  `alembic current`, start the API and verify `/health`, sign in, and open a referral and
  one of its documents.

## Release procedure

1. CI green: backend (SQLite and PostgreSQL), frontend, end-to-end.
2. Build images; run `alembic upgrade head` as a one-off task.
3. Roll the API, then workers, then web. Migrations must be backward compatible with the
   previous release during the roll.
4. Smoke test: `/health`, sign in, open the queue, `/metrics` scrape.

## Incident response (outline)

1. **Detect:** alert, audit anomaly or staff report. Record the start time and the
   `request_id` values involved.
2. **Contain:** disable affected accounts (Admin → People), revoke integration
   credentials, set `AB_LLM_PROVIDER=deterministic`, or pause workers.
3. **Investigate:** the audit log (`/v1/audit-events`) shows actor, operation, record,
   outcome and authority for every access and action.
4. **Notify:** follow the customer's breach-notification procedure and the business
   associate agreement; legal and privacy decide on notification.
5. **Recover and review:** fix, restore if needed, and write a post-incident review with
   corrective actions.

## Capacity notes

At pilot scale (spec target: 20 organizations, 100,000 referrals a month) the single
PostgreSQL instance is ample. The latency check shows reads under 10 ms at p95 with 3,000
referrals, and dashboard metrics about 130 ms. Dashboard metrics are computed in Python per
request and grow linearly with referrals. Move them to SQL aggregates or a nightly
materialized view before a single organization exceeds about 50,000 open referrals. The
in-process rate limiter should move to Redis when the API runs as several instances.
