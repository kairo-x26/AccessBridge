# Acceptance evidence

The requirements (§14) define pre-production gates. This page maps each gate to the
automated checks that cover it, and records results measured on synthetic data during
development. They are engineering results, not pilot results.

| Gate (spec §14) | Check | Result |
|---|---|---|
| **Functional**: every imported referral creates a traceable workflow record | `test_acceptance.py::test_every_import_creates_a_traceable_record`; FHIR and CSV intake tests | Pass: each import has an `imported` event citing its source and an audit record |
| **Extraction**: ≥95% precision and recall on critical fields | `app/evaluation/extraction.py` on 300 synthetic documents; `test_document_ai.py` | **100% / 100%** on clinic-template wording. Unseen wording: **100% precision, 25% recall** (fields are reported missing, not guessed) |
| **Workflow**: no invalid state transitions | Exhaustive 10×10 transition table (`test_state_machine.py`); 400-step random walk through the API with history replay | Pass: no invalid transition accepted; every stored event replays against the rules |
| **Agent safety**: zero unauthorized external actions | A hostile model proposes transmissions to foreign providers, messages and completions across all workflows (`test_no_external_action_without_authority`); prompt-injection document test | Pass: 0 transmissions, 0 messages sent, 0 completions without approval |
| **Tenant isolation**: all cross-tenant attempts rejected | Sweep of every id-addressed route (from the OpenAPI schema) as administrator, coordinator and security roles of another tenant; per-feature isolation tests | Pass: every attempt rejected (401/403/404/422); no record content leaked |
| **Integration**: retries and duplicates create no duplicate active work | Same FHIR bundle, signed webhook and Task update delivered 3× (`test_redelivered_inputs_create_no_duplicate_work`); crash-after-send redelivery test | Pass: counts unchanged after the first delivery; the receiver gets one message per key |
| **Reliability**: failed requests retried or surfaced | Flaky destination retried to success; unavailable destination dead-lettered → referral Exception + task; provider outage returns 503 with nothing sent | Pass: no failure reported as success |
| **Auditing**: every external action links actor, authority and result | `test_every_external_action_is_attributable` | Pass: each has an `approval:<id>:user:<id>` authorization, one success audit record with the result, and the approval decision on record |
| **Performance**: p95 reads < 500 ms | `tests/perf/test_read_latency.py` with 3,000 referrals | Queue page 3.7 ms, search 7.7 ms, detail 2.3 ms, tasks 2–3 ms, dashboard metrics 129 ms (SQLite, laptop) |
| **Usability**: supported flows without workarounds | Playwright journeys: sign-in, package review with evidence highlighting, approval to transmission receipt, policy assistant, invitation, role restrictions | Pass (9 tests). WCAG 2.2 AA axe scans: 0 violations on 11 light-mode screens (including the referral workspace) and 5 dark-mode screens |

## Test inventory

| Suite | Count | Runs on |
|---|---|---|
| Backend (unit, API, workflow, acceptance) | 278 | SQLite and PostgreSQL |
| Backend latency | 1 | on demand (`-m perf`) |
| Frontend components (Vitest + axe) | 13 | jsdom |
| End-to-end (Playwright) | 9 | production build + seeded backend + worker |

## Not covered by automated tests

* Real EHR, exchange and SMS vendors (simulated).
* Load beyond a single node; multi-instance rate limiting.
* Pilot usability with real coordinators; the requirements call for observed sessions.
