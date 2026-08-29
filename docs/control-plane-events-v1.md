# Control-plane public events V1 (ORCH-70)

This contract is the deterministic, executive-safe integration boundary for
mission status, budget/audit decisions, executive messages, handoffs, evidence,
and confidence. It is a projection over the append-only control-plane audit log;
raw audit detail is never returned.

## Envelope

Every history item and SSE `data` record has the same object:

```json
{
  "contract": "orch.control-plane.event",
  "contract_version": "1.0",
  "id": "server-event-id",
  "cursor": "v1.opaque-cursor",
  "type": "mission_status",
  "occurred_at": "2026-08-08T00:00:00.000Z",
  "source": "control_plane",
  "org_id": "example-org",
  "mission_id": "mission-id",
  "visibility": "executive_safe",
  "data": {}
}
```

Server-owned fields cannot be supplied by publishers. V1 event types are:

- `mission_status`: status, previous status, terminal flag, optional reason code.
- `budget_audit_decision`: budget action/outcome and allowlisted integer-cent fields.
- `executive_message`: severity, bounded safe summary, action-required flag.
- `handoff`: opaque ID, stable role references, status, safe summary, evidence IDs.
- `evidence`: opaque evidence/reference IDs, kind, label, verification status.
- `confidence`: subject, integer score from 0–100, computed band, enumerated basis.

Role fields are stable slugs/references, not display names; an ORCH-71 adapter
must map names containing spaces or `/`. Evidence kinds include ORCH-71's
`automated_test`, `ui_test`, `visual_review`, and `independent_review` vocabulary.

Mission status and budget decisions are control-plane-owned facts. The publish
endpoint accepts only the other four types with strict fields; unknown fields
fail closed.

## Authorization and safety boundary

All endpoints are nested under the existing API-secret-protected router. The
service authorization port checks capabilities and, when given a tenant-scoped
principal, the mission organization before reading or publishing. An
organization mismatch is returned as not found.

The current shared API key is honestly modeled as an operator-wide legacy owner,
not as multi-tenant authorization. Organization and capabilities are never read
from client headers. ORCH-69 must later supply a trusted tenant-scoped
`EventAccess` principal.

The public projector never copies raw audit detail, actor, mission brief, notes,
worker metadata, prompts, provider responses, private reasoning, credentials,
tokens, authorization headers, cookies, or browser/session data. External event
fields are allowlisted, unknown sensitive structures are rejected, and
credential-shaped text is scrubbed before persistence. Trusted adapters must
submit already-classified operational summaries; raw model or provider output
must never be passed to the publish endpoint.

## History and stream

History:

```text
GET /api/control-plane/v1/missions/{mission_id}/events?after={cursor}&limit=100
```

Results are ascending and resumable. `next_cursor` is the final returned cursor;
passing it as `after` never repeats that event.

Stream:

```text
GET /api/control-plane/v1/missions/{mission_id}/events/stream
Last-Event-ID: {cursor}
```

SSE `id` equals the event cursor. Backlog and live polling use the same durable
history reader and serializer; idle streams receive comment heartbeats.
`once=true` is a finite demo/test mode. Keep API
credentials in headers—never in a URL or query parameter.

The V1 SQLite adapter hides append-only `rowid` behind the opaque cursor. A
future PostgreSQL adapter may substitute its own monotonic sequence. Rebuilding
the SQLite audit table could invalidate old cursors; that is a known pre-cutover
limitation. V1 publishing has no caller idempotency key, so producers must avoid
blindly retrying a successful POST; consumers should deduplicate by event ID.

## Minimal demo

Use non-secret placeholders in a local environment:

1. Create and start an `example-org` mission with the existing mission endpoints.
2. Reserve a small budget amount to create a budget decision.
3. Publish the four integration events, for example:

```bash
curl -X POST "$BASE/api/control-plane/v1/missions/$MISSION_ID/events" \
  -H "X-Api-Key: $API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"type":"executive_message","data":{"summary":"Planning complete","severity":"info","action_required":false}}'
```

Use the corresponding strict data fields above for `handoff`, `evidence`, and
`confidence`, then compare:

```bash
curl "$BASE/api/control-plane/v1/missions/$MISSION_ID/events" \
  -H "X-Api-Key: $API_SECRET"

curl -N "$BASE/api/control-plane/v1/missions/$MISSION_ID/events/stream?once=true" \
  -H "X-Api-Key: $API_SECRET"
```

The JSON objects in history and SSE `data` are identical.
