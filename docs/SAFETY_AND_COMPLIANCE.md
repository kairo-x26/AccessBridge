# Safety, privacy and compliance

AccessBridge AI is a **proposed product** built and tested with **synthetic data only**.
Nothing here claims HIPAA compliance, SOC 2 or any certification, and the platform has no
customers or deployments. This document maps the controls the requirements ask for
(§11–§12) to what the code does, and lists what a real deployment still needs.

## Scope boundary

AccessBridge coordinates **administrative** steps. It does **not** diagnose, set or change
clinical urgency, recommend treatment, or make consequential decisions without a person.

How the code holds that line:

* Urgency is stored only as `priority_from_source`, exactly as the referring clinician
  stated it; no code path writes it afterwards.
* Checklists check administrative completeness; nothing scores clinical need.
* Patient messages come only from reviewed templates that are checked for clinical wording.
* Replies that mention symptoms, medications, results or urgency are escalated to clinical
  staff with no automated answer.
* The policy assistant answers only from approved procedures and never gives clinical
  advice.

## AI controls (spec §11)

| Requirement | Implementation | Verified by |
|---|---|---|
| Never fabricate values | Extracted values are stored only if the cited span reproduces them exactly; the model returns quotes and the code locates them; explicit blanks are treated as missing | `test_document_ai.py`, `test_agents.py::test_llm_extraction_is_grounded` |
| Preserve evidence | Every field keeps document id and character span; the UI highlights the source | `test_review_api.py`, e2e evidence test |
| Ground factual outputs | Policy answers cite provided passages or say "not found"; model answers with invalid citations are discarded | `test_policies.py` |
| Treat uploaded and retrieved text as untrusted | Documents never reach the planner; extraction output is restricted to field/quote pairs; retrieved passages are wrapped as data, and instruction-like passages are flagged and withheld from models | `test_prompt_injection_cannot_widen_tool_scope`, `test_injected_passages_are_flagged_and_never_used` |
| Injection can't control authorization or tool scope | Deterministic policy engine: workflow allowlists, strict argument schemas, allowed states, tenant-scoped ids; confidence is not an input | `test_policy_and_gateway.py`, `test_acceptance.py::test_no_external_action_without_authority` |
| Escalate identity mismatches and ambiguity | Identity mismatch blocks approval and can't be waived; shared phone numbers and unknown senders go to people; consult notes for another patient create a task | `test_review_api.py`, `test_messaging.py` |
| Limit tokens, tool calls, runtime and external scope | Per-run token budget, 8 tool calls, 1 external action; job leases and retry caps | `test_usage_is_metered_and_budget_enforced`, policy tests |
| Log model, prompt and tool versions and decisions | Agent runs record workflow and model versions; every proposal is stored with decision and reason; model calls are metered per task; extraction version is stored per field | `AgentRun`, `AgentAction`, `LLMUsage` |
| Confidence never grants permission | `policy.evaluate` has no confidence parameter | `test_confidence_is_not_an_input` |

## Security controls (spec §12)

| Control area | Implementation | Deployment still needs |
|---|---|---|
| Authentication | scrypt password hashing, 12+ character policy, lockout after 5 failures, TOTP two-step verification (org-wide enforceable), 30-minute tokens, rate-limited sign-in | Enterprise SSO (OIDC/SAML); the `auth_identity` field is in place |
| Authorization | Role-permission matrix; every endpoint declares permissions; tokens re-validated against current role and status | Access reviews |
| Tenant isolation | Organization filter on every tenant query; cross-tenant ids return not found; automated sweep of every id route | Penetration test |
| Encryption in transit | HSTS in production; TLS terminated at the edge | TLS certificates and configuration |
| Encryption at rest | Field-level Fernet encryption for contact details, birth date, extracted values, document text and messages; encrypted document files | KMS-managed keys; encrypted database and volumes |
| Secrets | Production refuses development secrets; secrets only from environment | Secret manager with rotation |
| Data minimization | Role-filtered patient views (clinicians don't see contact details); PHI redaction in logs; model prompts redact contacts and the planner gets ids and counts only; audit stores references and question fingerprints, not text; exports are aggregate with small-cell suppression | Data-flow review per deployment |
| LLM privacy | Model calls are off by default (`deterministic`); no training on customer data is configured or implied | BAA and zero-retention terms with the model vendor before enabling |
| Audit | Append-only audit events for sign-ins, data access, document reads, transitions (including rejected ones), proposals, approvals, actions, messages and configuration | Log shipping to tamper-evident storage |
| Patient messaging | Consent reference, verified contact, preferred channel, reviewed templates, opt-out, resend window, signed webhooks with replay window | Carrier registration (10DLC), TCPA review |
| Retention | Configurable per organization, daily purge of working data, legal holds | Retention schedules agreed per contract and state law |
| Backups | Documented RPO/RTO and restore test procedure | Implemented backups and tested restores |
| Web security | CSP, frame denial, nosniff, no-referrer, httpOnly SameSite=Strict session cookie, request size limit | WAF |

## Before any real patient data

AccessBridge would generally act as a **business associate** to covered-entity clinics.
Before handling PHI, a deployment needs at least:

1. A HIPAA security risk analysis and documented safeguards.
2. Business associate agreements with each customer and each subprocessor that touches PHI
   (hosting, messaging provider, model provider if enabled).
3. Production infrastructure per the operations runbook, with KMS, backups, monitoring and
   tested restores.
4. Penetration testing and an access review.
5. Clinical-operations review of escalation wording, templates and checklists with the
   pilot clinic.
6. Staff training and an incident response plan.

## Known limitations

* **Extraction recall drops on unfamiliar form wording** (about 25% on the unseen-label
  corpus, with precision still 100%). Unfamiliar forms create *missing* tasks rather than
  wrong values. Model-assisted extraction or per-clinic label patterns would improve recall.
* **OCR is not included.** Scanned images go to a person.
* **Integrations are simulated.** The FHIR adapter parses and reconciles real R4 shapes, but
  no vendor EHR, exchange network or SMS carrier has been connected.
* **Rate limiting is in-process.** It needs Redis for multiple API instances.
* **The reply classifier is keyword-based.** It is tuned to escalate rather than miss;
  unusual phrasing becomes "needs reading" for a person.
