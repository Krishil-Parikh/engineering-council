# Workspace Backend Contract

The frontend treats the backend as an interchangeable transport behind
`src/repositories/WorkspaceRepository.ts`. This document is the agreement the
backend team builds against. It mirrors `HttpWorkspaceRepository`,
`mapSnapshotHttpError`, `validateWorkspaceCommand`, and the provider status
mapping exactly — if code and doc disagree, the doc is updated, never the
other way around without a contract version bump.

## Transports

| `VITE_TRANSPORT` | Snapshot | Commands | Events |
|---|---|---|---|
| `mock` (default) | in-memory seed | in-memory, same reducer | central simulation loop |
| `http-sse` | `GET /workspace/{id}/snapshot` | `POST /workspace/{id}/commands` | `GET /workspace/{id}/events` (SSE) |
| `http-websocket` | same as `http-sse` | same as `http-sse` | same URL over WebSockets |

`{base}` is `VITE_API_BASE_URL` (no trailing slash); `{id}` is URL-encoded.
`POST` sends `Content-Type: application/json` with the command as the body and
expects a `CommandResult` (`{ accepted, commandId }`) as JSON.

## Snapshot

`GET /workspace/{id}/snapshot` returns a `WorkspaceSnapshot` (see
`src/domain/types.ts`): `workspaceId`, `version`, `phaseId`, `agents`,
`messages`, `skills`, `artifacts`, `meets`, `sprints`, `edges`, `metrics`,
`processedEventIds`. The client validates shape and rejects the payload with
`Workspace snapshot failed validation` when required fields are missing —
the backend must return the full shape, never partial entities.

Artifact richness is progressive: `versions[]` (per-version author, timestamp,
summary, diff additions/deletions, sign-offs), `markdownContent`, and
`acceptedBy` are **optional**. Metadata-only artifacts render with graceful
fallbacks; backends can start metadata-only and add bodies later without a
contract bump.

## Events

Every event carries `{ eventId, workspaceId, occurredAt, version }` plus a
discriminated `type`/`payload`. Catalog (`src/domain/types.ts`):

- `agent.updated` / `skill.updated` / `artifact.updated` / `meet.updated` /
  `sprint.updated` / `edge.updated` — upsert by `payload.id`.
- `message.created` — append; duplicate message `id`s are ignored.
- `phase.changed` — `{ phaseId }`.
- `metrics.updated` — replaces `metrics`.

Delivery rules the backend must honor:

- `eventId`s are unique and idempotent: redelivery must be safe, the client
  drops repeats.
- `version` is monotonically increasing per workspace. The client drops events
  with `version` below its snapshot version; equal versions with new ids still
  apply.
- Malformed JSON frames surface as `Workspace event was not valid JSON`;
  well-formed but shapeless frames as `Workspace event was malformed`. Neither
  corrupts state — the client keeps the last good snapshot.

## Commands

Catalog (`src/domain/commands.ts`, validated client-side before POST):

- `sprint.start` `{ workspaceId, brief }` — `brief` non-empty.
- `phase.advance` `{ workspaceId, phaseId }`.
- `agent.task.reassign` `{ workspaceId, agentId, task }` — both non-empty.
- `message.create` `{ workspaceId, message: { meetId, senderId, senderName, text, timestamp } }`.
- `sme.directive.submit` `{ workspaceId, meetId, directive }`.
- `prd.accept` `{ workspaceId, artifactId }`.
- `debate.inject` `{ workspaceId, meetId, text }`.
- `consensus.force` `{ workspaceId, meetId }`.

Validation failures return 4xx with a machine-readable error; the UI surfaces
the message and keeps workspace state.

## Errors → UI states

| Backend signal | Client error | UI status |
|---|---|---|
| 401 / 403 on snapshot | `Workspace snapshot failed: 401 Unauthorized` / `403 Forbidden` | `permission-denied` + Retry |
| 404 / 409 / 429 / 5xx | `Workspace snapshot failed: {status} …` | `error` + Retry |
| timeout (10s default) | `Workspace request timed out after {ms}ms` | `error` + Retry |
| stream drops, retries exhausted (5, backoff 1s × 2ⁿ) | `Workspace event stream disconnected` | `disconnected` banner, cached state stays visible + Reconnect |
| stream framing error | `… malformed …` | `stale` banner + Refresh |
| command POST fails / validation fails | `Workspace command failed…` / `Invalid command…` | command-failure banner, state kept |

## Auth and secrets

Authentication lives server-side (cookies / gateway). The client sends no
secrets: `VITE_*` variables carry only URLs, ids, and feature flags.
Do not accept API keys from the frontend.

## Open questions for the backend (TBD)

Pagination, rate-limit quotas, and event retention/replay windows. Until
decided, the client assumes: full-snapshot loads, no pagination, and streams
that resume best-effort with idempotent redelivery.

## Bring-up checklist

1. Implement the three endpoints per `contracts/openapi.workspace.stub.yaml`.
2. Run `src/repositories/workspaceRepository.contract.test.ts` against staging
   (same suite the mock passes).
3. Set `VITE_TRANSPORT=http-sse`, `VITE_API_BASE_URL`, `VITE_WORKSPACE_ID`.
4. Exercise failure paths: 401/403/404/429/500, disconnect, malformed frame,
   duplicate delivery — the `WorkspaceShell.states` tests pin the UI side.
5. Keep mock green in CI; mock remains the default for local UI work.
