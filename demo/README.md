# AccessBridge demo

A synthetic community health center, **Riverbend Community Health**, with staff in every
role, eight specialist offices and sixteen referrals spread across every stage of the
route. All people, identifiers and clinical text are fictional.

## Start it

```bash
./demo/run_demo.sh          # seeds fresh data, starts API, worker and web app
./demo/run_demo.sh --keep   # restart without reseeding
```

Requires `uv` and `pnpm` (see the [developer guide](../docs/DEVELOPER_GUIDE.md)). Open
<http://localhost:3000> and sign in to organization **riverbend** with password
**Demo-Password-2026**:

| Account | Role | Good for |
|---|---|---|
| `priya.coordinator@riverbend.example.org` | Referral coordinator | Queue, package review, approvals |
| `tomas.coordinator@riverbend.example.org` | Referral coordinator | A second owner |
| `grace.navigator@riverbend.example.org` | Patient navigator | Messages and replies |
| `dana.admin@riverbend.example.org` | Administrator | Dashboard, admin console |
| `marcus.admin@riverbend.example.org` | Administrator | Second reviewer for templates and policies |
| `amara.clinician@riverbend.example.org` | Clinician | Read-only status, completion notifications |
| `ivy.security@riverbend.example.org` | Security administrator | Audit log |

## Narrated walkthrough (terminal)

With the demo running, in a second terminal:

```bash
cd backend && uv run python ../demo/scenario.py          # pauses before each step
cd backend && uv run python ../demo/scenario.py --auto   # runs straight through
```

It takes a new referral for "Elena Ruiz" from EHR import to completed care over the API,
printing the route after each step, then shows the safety behaviour. Keep the web app open
alongside; the referral link is printed at the end.

## Ten-minute guided tour (web app)

**1. The queue (coordinator).** Sign in as Priya. Each row's route line shows where the
referral is. Find the amber diamond (Samuel Brooks: the specialist's system was down and
the package couldn't be delivered) and the end bar (Noah Petrov: declined). Switch views
and search "rosa".

**2. A package in review.** Open **Grace Okafor**. The checklist shows what's present;
*What the documents say* lists each value with **Show in referral-letter.txt**. Click it,
and the exact source text is highlighted. Dashed violet values were read automatically;
**Confirm** turns them solid. Confirm the four "must confirm" fields, then **Approve
package**.

**3. Nothing leaves without a person.** Within seconds the agent proposes **Send package
to specialist**: a dashed violet stop on the route and a card in **Approvals**. Approve
it; the stop turns solid with a *Transmission receipt*. (Luis Moreno is already waiting at
this step.)

**4. The evidence rule.** On any scheduled referral, open **Record a change**, choose *Care
completed* and look at the evidence choices: a consult note or the specialist's
confirmation. Message delivery isn't offered, and the API rejects it.

**5. Patient replies (navigator).** Sign in as Grace. **Replies** shows Ivy Romero asking
for transportation help in Spanish, with a high-priority task. Open her referral to see
the Spanish reminder that was sent and the classified reply.

**6. Closing the loop.** Rosa Delgado's cardiology referral shows the whole route,
ending green with the specialist's consult note. Sign in as Amara (clinician) and open
the bell: completed referrals notify the referring team.

**7. Policies.** Ask *"What should I do if a patient texts back about symptoms?"* The
answer quotes the messaging policy with a numbered source. Ask about visitor parking and it
says it doesn't know. In the library, *Specialist office contact notes* is flagged: it
contains an injected instruction, which is never sent to a model.

**8. Dashboard and admin (administrator).** Sign in as Dana. The dashboard leads with
verified completed care, then shows waiting time, where referrals are, and how often staff
approve the agent. **Admin → Organization** shows that only reviewed reminder texts can
ever be pre-approved.

**9. Audit (security).** Sign in as Ivy (security): every view, document read, proposal,
approval and send is listed with who, what authority and what result.

## Try intake yourself

Files in `demo/data/`:

| File | Use |
|---|---|
| `sample-fhir-import.json` | `POST /v1/referrals/import` body (see [API guide](../docs/API.md)) |
| `sample-referrals.csv` | **Add referrals → Import a CSV export**: three rows import, one is rejected for its date format |
| `referral-letter.txt` | Upload to a referral with **Add document** |
| `consult-note.txt` | Upload to Marcus Ellery's referral after importing the FHIR sample and moving it to *Scheduled* |

Simulators for the parts of the world the demo doesn't have (development only):

```bash
# patient texts back
curl -X POST localhost:8000/v1/dev/simulate/patient-reply -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"phone":"+1 555 010 2231","body":"1"}'
# specialist system schedules the visit
curl -X POST localhost:8000/v1/dev/simulate/specialist-update -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"service_request_id":"SR-2026-1042","status":"in-progress","appointment":"2026-11-03T09:00:00-06:00"}'
# what the SMS gateway "sent"
curl localhost:8000/v1/dev/simulate/outbox -H "Authorization: Bearer $TOKEN"
```

The specialist office **Northgate GI Partners** fails its first delivery attempt and
**Harbor Behavioral Health** is always down, so you can watch retries and
failure handling.
