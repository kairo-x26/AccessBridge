# API guide

The API is REST over JSON under `/v1`. The interactive reference (OpenAPI) is at
`http://127.0.0.1:8000/docs` in development; production hides it. The frontend's TypeScript
types are generated from the same schema (`pnpm gen:api`).

## Authentication

```http
POST /v1/auth/login
{"organization": "riverbend", "email": "…", "password": "…"}

→ {"access_token": "…", "token_type": "bearer"}
→ or {"mfa_required": true, "mfa_challenge": "…"}

POST /v1/auth/mfa/verify
{"challenge": "…", "code": "123456"}
```

Send `Authorization: Bearer <token>` on every other request. Tokens last 30 minutes and are
re-validated against the user's current role and status on each call. The web app never
exposes this token to the browser (the BFF holds it in an httpOnly cookie).

## Conventions

| Topic | Behaviour |
|---|---|
| Errors | `{"error": {"code": "…", "message": "…", "details": {…}}}` with 401, 403, 404, 409, 413, 422, 429 or 503. Request-shape errors use FastAPI's `{"detail": [...]}`. |
| Tenancy | Records outside your organization return **404**, never 403. |
| Idempotency | `Idempotency-Key` header on imports, status events and sends: a repeat returns the original response (`idempotent-replay: true`); reusing a key with a different body returns 409. |
| Concurrency | Mutations that change a referral accept `expected_version`; a stale version returns 409 with the current version. |
| Pagination | `page`, `page_size` (max 100) → `{items, total, page, page_size}`; the audit log uses `before` cursors. |
| Tracing | Send or receive `x-request-id`; `server-timing` reports server time. |
| Rate limits | 429 with `details.retry_after_seconds` on sign-in, MFA, invitations, webhooks and policy questions. |

## Endpoints

### Specification endpoints (requirements §9)

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/v1/referrals/import` | Ingest an authorized FHIR R4 bundle (ServiceRequest, Patient, DocumentReference) | `referral:import` |
| GET | `/v1/referrals` | Filter (status, specialty, owner, `q`) and paginate | `referral:read` |
| GET | `/v1/referrals/{id}` | Authorized referral view (contact details by role) | `referral:read` |
| POST | `/v1/referrals/{id}/analyze` | Queue extraction, validation and agent planning (`workflow`: intake, follow_up, completion) → `{run_id, job_id}` | `agent:run` |
| GET | `/v1/agent-runs/{id}` | Run progress, proposals, decisions and approvals | `referral:read` |
| POST | `/v1/approvals/{id}/decision` | Approve or reject a pending agent action (`reason` required to reject) | `action:approve` + tool permission |
| POST | `/v1/referrals/{id}/status-events` | Record an evidence-backed transition | `referral:transition` (corrections: admin) |
| GET | `/v1/reports/referrals` | Operational metrics with definitions | `report:read` |

### Intake, documents and review

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/referrals/import/csv` | CSV intake (multipart `file`) |
| POST | `/v1/referrals` | Manual intake |
| PATCH | `/v1/referrals/{id}` | Owner, destination, specialty (with `expected_version`) |
| POST | `/v1/referrals/{id}/documents` | Upload PDF, text or image (≤10 MB); starts the completion agent for referrals already sent |
| GET | `/v1/documents/{id}/content`, `/text` | Original file / extracted text (audited) |
| GET | `/v1/referrals/{id}/fields` | Extracted values with spans, confidence and method |
| PATCH | `/v1/fields/{id}` | `accept`, `correct` (with value) or `reject` |
| GET | `/v1/referrals/{id}/validation` | Checklist, issues and approval readiness |
| POST | `/v1/validation-issues/{id}/waive` | Waive an optional issue with a reason |
| GET / POST | `/v1/referrals/{id}/package`, `/package/approve` | Preview and approve the package snapshot |
| GET | `/v1/referrals/{id}/packages` | Approved package versions |
| POST | `/v1/referrals/{id}/analyze/sync` | Inline analysis (small uploads, tests) |
| POST | `/v1/referrals/{id}/legal-hold` | Place or lift a legal hold (admin) |

### Work, people and settings

| Area | Paths |
|---|---|
| Tasks | `GET/POST /v1/tasks`, `PATCH /v1/tasks/{id}` |
| Approvals | `GET /v1/approvals?status=pending\|approved\|rejected`, `GET /v1/referrals/{id}/agent-runs` |
| Messaging | `GET /v1/referrals/{id}/communications`, `POST …/communications/preview`, `POST …/communications`, `GET /v1/communications/inbox`, `POST /v1/communications/{id}/resolve`, `PATCH /v1/patients/{id}/contact` |
| Templates | `GET /v1/templates`, `PUT /v1/templates/{key}/{language}`, `POST /v1/templates/{id}/review` |
| Checklists | `GET /v1/checklists`, `PUT/DELETE /v1/checklists/{specialty}` |
| Providers | `GET/POST /v1/providers`, `PUT /v1/providers/{id}` |
| Policies | `GET/POST /v1/policies`, `GET /v1/policies/{id}`, `POST …/approve`, `POST …/archive`, `POST /v1/policies/ask` |
| Users | `GET /v1/users`, `GET /v1/users/staff`, `POST /v1/users/invitations`, `PATCH /v1/users/{id}`, `POST /v1/auth/accept-invitation` |
| Account | `GET /v1/auth/me`, `POST /v1/auth/mfa/setup`, `POST /v1/auth/mfa/enable` |
| Organization | `GET/PATCH /v1/organization` |
| Reports | `GET /v1/reports/referrals`, `GET /v1/reports/referrals.csv` |
| Audit | `GET /v1/audit-events` |
| Notifications | `GET /v1/notifications`, `POST /v1/notifications/{id}/read` |
| Operations | `GET /v1/ops/jobs`, `POST /v1/ops/jobs/{id}/retry`, `GET /health`, `GET /metrics` |

### Integrations

**FHIR Task updates** (specialist systems): `POST /v1/integrations/fhir/task-updates` with
`{"resources": [Task, …]}`. Each result is `applied`, `duplicate`, `stale`, `conflict`,
`review`, `unmatched` or `invalid`. Status mapping: `received`/`accepted` → acknowledged;
`in-progress` with an appointment or a "scheduled" business status → scheduled; `completed`
with a report reference → completed (without one, a person reviews); `rejected` → declined;
`cancelled` → cancelled; `failed` → exception. Updates never move a referral backwards or
out of an exception or closed state.

**Messaging webhooks**: `POST /v1/webhooks/messaging`, with no bearer token, signed with
`x-ab-timestamp` and `x-ab-signature = hex(HMAC-SHA256(secret, timestamp + "." + body))`.
Requests older than five minutes are rejected; events are deduplicated by `event_id`.

```json
{"type": "delivery", "event_id": "ev-1", "message_id": "sm_…", "status": "delivered"}
{"type": "inbound", "event_id": "ev-2", "account": "riverbend", "from": "+15550102231", "body": "1"}
```

**Development simulators** (absent in production): `POST /v1/dev/simulate/patient-reply`,
`/delivery`, `/specialist-update`, and `GET /v1/dev/simulate/outbox`.

## Example: import and follow a referral

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/login -H 'content-type: application/json' \
  -d '{"organization":"riverbend","email":"priya.coordinator@riverbend.example.org","password":"Demo-Password-2026"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/v1/referrals/import -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -H 'Idempotency-Key: demo-1' \
  -d @demo/data/sample-fhir-import.json
# → {"imported": ["ref_…"], "duplicates": [], "exceptions": [], "errors": []}

curl -s -X POST localhost:8000/v1/referrals/ref_…/analyze -H "Authorization: Bearer $TOKEN"
# → {"run_id": "run_…", "job_id": "job_…", "status": "queued"}
```
