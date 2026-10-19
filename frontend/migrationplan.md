# Frontend Migration Plan

## Goal

Turn the current two-UI prototype into one maintainable, backend-agnostic frontend:

- One application shell with the `GenUI` and `Control Plane` views.
- One shared workspace model and one source of truth for sprint state.
- One repository boundary for snapshots, commands, and live events.
- Mock and real backends interchangeable without changing UI components.
- Modular, extensible, configurable code that can support additional views later.
- Existing visual design, animations, spacing, and workflows preserved.

This plan is intentionally incremental. Each phase leaves the app runnable and has a verification gate.

## Implementation Status

Completed and verified in the current migration slice (`npm run lint`, `npm run test` — 58 passing, `npm run build`, `npm run test:e2e` — 4 passing, all green):

- Vitest test harness and test scripts, plus jsdom component tests and a Playwright browser smoke suite (`test:e2e`).
- Immutable workspace event reducer with duplicate/stale event protection, entity upserts for previously unknown ids, same-version convergence, and bounded processed-event history.
- Canonical workspace types, commands, and selectors. Events now cover agents, messages, phases, artifacts, meets, metrics, skills, sprints, and delegation edges. Commands cover sprint start, phase advance, task reassign, message create, SME directive submit, PRD accept, debate inject, and consensus force, with shared validation used by both repositories.
- Deterministic workspace fixtures: empty, active sprint, blocked agent, completed sprint, and partially accepted artifact.
- Runtime snapshot validation at the HTTP repository boundary.
- Mock repository and shared repository contract suite run against both mock and HTTP repositories.
- HTTP snapshot/command repository with SSE subscription boundary, request timeouts, typed permission/conflict/rate-limit errors, reconnect with backoff, and duplicate/malformed event guards.
- Centralized demo simulation adapter with a single loop owned by the shell; all view-level data-generation timers removed (remaining timers are presentational with cleanup).
- Typed runtime configuration for mock versus HTTP/SSE/WebSocket transport.
- Shared workspace store/provider mounted at the host composition root. The provider loads before subscribing (no load/subscribe race), maps failures to loading/error/permission-denied/disconnected/stale states, keeps cached state visible on disconnect, and surfaces command failures.
- Host shell boundary: `WorkspaceShell` composition root, `ViewRegistry` view map, `views/GenUIView` and `views/ControlPlaneView`. The sibling Control Plane is consumed through one adapter module; React is aliased to a single copy.
- GenUI reads agents, skills, transcript, PR metrics, and phase from the shared snapshot and issues canonical commands; only navigation, overlays, and presentational flags stay local.
- Control Plane `ScrumContext` derives agents/messages/meets/artifacts/sprints/edges/skills from the shared snapshot and routes debate, SME intervention, consensus, reassignment, and manual simulation steps through repository commands.
- No view imports `INITIAL_*` data or calls browser network APIs. Static GenUI reference documents live in view-owned content, not the repository seed layer.
- Loading, empty, error, disconnected, permission-denied, stale, and command-failure UI states, all covered by tests.
- Desktop and narrow viewport screenshots for both modes captured under `e2e/screenshots/` as the visual baseline; browser smoke asserts zero uncaught page errors.

Superseded by `migration_planv2.md` (executed, all phases green — see below).
The v1 end-state held at commit `217b3e1`, then:

- Single project: the sibling `the-deck-—-agentic-scrum-control-plane` project
  is deleted. The Control Plane view lives at
  `src/views/control-plane/` (pure `ControlPlaneView` + connected
  `WorkspaceControlPlaneView`), moved with `git mv` history intact.
- One `npm install`, one React 19.3.0, pruned manifest (`express`,
  `@google/genai`, `dotenv`, `tsx`, `@types/express` removed as provably unused).
- Host-owned cascade: sibling utilities/keyframes merged into `src/index.css`;
  sibling entry/CSS deleted.
- Lazy-split views: entry chunk ~994 kB (was ~1,208 kB) + separate
  `WorkspaceControlPlaneView` chunk ~215 kB.
- Backend seam: `createRepositoryFromConfig()`, documented `VITE_*` env,
  `docs/backend-contract.md`, `contracts/openapi.workspace.stub.yaml`.
- Final gates: `lint` clean, 60/60 vitest, `vite build`, 4/4 Playwright,
  screenshots reviewed with no unintended delta.

Still required before calling the migration complete:

- Real backend implementation against the contract (OpenAPI stub →
  authoritative spec, typed client generation, CI schema-drift detection).
- Screenshot-comparison CI on top of the captured baselines, plus reduced-motion and full keyboard-path audits beyond the mode tabs.

## Current State

> Historical snapshot of the pre-migration prototype. As of `migration_planv2.md`,
> there is one project, one shared store, and no sibling directory. The risks
> below are retained as the record of what was fixed.

The `frontend/agentic-scrum-control-plane` project currently hosts the combined app and directly imports the sibling Control Plane app from `the-deck-—-agentic-scrum-control-plane`.

Current risks:

- GenUI owns state locally in `src/App.tsx`.
- Control Plane owns a separate state machine in its own `src/context/ScrumContext.tsx`.
- The two apps have different domain types and mock data models.
- Both apps run local simulation timers.
- The host imports the sibling app by filesystem path rather than consuming a shared package/module contract.
- Tailwind scans and CSS rules are split across the two source trees.
- Backend calls, event subscriptions, and UI concerns have no explicit boundary.
- State updates are vulnerable to accidental mutation. The observed error at `src/App.tsx:149` (`last.prs += 1`) must be fixed before live data is introduced.
- There is currently no automated test runner or behavior test suite.

## Target Architecture

```text
src/
  app/
    App.tsx                 # composition root
    WorkspaceShell.tsx      # mode switcher and shared providers
    config.ts               # environment-safe runtime configuration
  domain/
    types.ts                # canonical workspace entities and event types
    commands.ts             # user intents sent to the repository
    selectors.ts            # derived read-only values
    reducers.ts             # deterministic event/state transitions
  state/
    WorkspaceProvider.tsx
    workspaceStore.ts
    workspaceContext.ts
  repositories/
    WorkspaceRepository.ts  # backend-agnostic interface
    MockWorkspaceRepository.ts
    HttpWorkspaceRepository.ts
    EventStream.ts          # SSE/WebSocket adapter, transport only
  adapters/
    genui/
    control-plane/
  views/
    GenUIView/
    ControlPlaneView/
  test/
    fixtures/
    contract/
    integration/
    visual/
```

The exact folders may be adjusted to match local conventions, but the dependency direction must remain:

```text
views -> state/domain
state -> repository interface
repositories -> transport/configuration
transport -> browser/network APIs
```

Views must not call `fetch`, `EventSource`, `WebSocket`, or import mock data directly.

## Canonical Domain Model

Define one model for shared concepts. The richer Control Plane model is the starting point, but the model should describe product concepts rather than a particular UI.

Minimum shared entities:

- `WorkspaceSnapshot`
- `Sprint`
- `Phase`
- `Agent`
- `Meet`
- `Message`
- `Artifact`
- `DelegationEdge`
- `WorkspaceMetrics`

Every live event should include:

```ts
interface WorkspaceEventBase {
  eventId: string;
  workspaceId: string;
  occurredAt: string;
  version: number;
}
```

Use discriminated unions for events:

```ts
type WorkspaceEvent =
  | (WorkspaceEventBase & { type: 'agent.updated'; payload: Agent })
  | (WorkspaceEventBase & { type: 'message.created'; payload: Message })
  | (WorkspaceEventBase & { type: 'phase.changed'; payload: { phaseId: PhaseId } })
  | (WorkspaceEventBase & { type: 'artifact.updated'; payload: Artifact })
  | (WorkspaceEventBase & { type: 'meet.updated'; payload: Meet })
  | (WorkspaceEventBase & { type: 'metrics.updated'; payload: WorkspaceMetrics });
```

Events must be idempotent. Duplicate `eventId` values must not change state twice. Stale event versions must not overwrite newer state.

## Repository Contract

Create the interface before connecting a real backend:

```ts
export interface WorkspaceRepository {
  getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot>;
  execute(command: WorkspaceCommand): Promise<CommandResult>;
  subscribe(
    workspaceId: string,
    onEvent: (event: WorkspaceEvent) => void,
    onError?: (error: Error) => void,
  ): () => void;
}
```

Commands should represent user intent, not UI implementation details:

```ts
type WorkspaceCommand =
  | { type: 'sprint.start'; workspaceId: string; brief: MissionBrief }
  | { type: 'sme.directive.submit'; workspaceId: string; directive: string }
  | { type: 'prd.accept'; workspaceId: string }
  | { type: 'agent.task.reassign'; workspaceId: string; agentId: string; task: string }
  | { type: 'debate.inject'; workspaceId: string }
  | { type: 'consensus.force'; workspaceId: string };
```

The UI should not know whether a command is implemented by REST, GraphQL, a workflow engine, or a local mock.

## Phased Migration

### Phase 0: Baseline and Safety

**Objective:** Freeze the current visual and behavioral contract before refactoring.

Tasks:

1. Confirm the combined host is the only runnable entry point.
2. Record desktop and narrow viewport screenshots for both modes.
3. Record the critical flows:
   - switch GenUI/Control Plane;
   - start a GenUI meet;
   - advance through GenUI phases;
   - switch Control Plane tabs;
   - inject debate;
   - open SME override;
   - reassign an agent task;
   - force consensus.
4. Fix all runtime errors before moving state:
   - replace in-place PR history mutation with an immutable update;
   - ensure every timeout/interval has cleanup;
   - decide whether React Flow attribution is licensed/configured rather than suppressing the warning.
5. Add a test command and a minimal test runner. Prefer Vitest with Testing Library for this Vite project.

**Exit criteria:** `npm run lint`, `npm run build`, and baseline behavior tests pass; no uncaught browser errors during the critical flows.

### Phase 1: Establish the Host Boundary

**Objective:** Make the shell a composition root without changing either view's behavior.

Tasks:

1. Move `WorkspaceMode` and the switcher into `src/app/WorkspaceShell.tsx`.
2. Rename the two current implementations as view-level components:
   - `GenUIView`
   - `ControlPlaneView`
3. Keep the switcher responsible only for selecting a view.
4. Keep CSS and Tailwind scanning owned by the host project.
5. Stop importing the sibling app's global stylesheet into the host.
6. Add a `ViewRegistry` or explicit view map so future views can be added without nesting mode conditionals throughout the app.

**Exit criteria:** Switching modes preserves the existing layout and animations; no view imports the other view; the host has one clear composition root.

### Phase 2: Define Canonical Domain Types

**Objective:** Remove duplicate domain definitions and give both views a shared language.

Tasks:

1. Create `src/domain/types.ts` from the combined concepts in both existing type systems.
2. Keep UI-only types local to each view.
3. Normalize naming, identifiers, timestamps, statuses, and phase IDs.
4. Add explicit nullable/optional fields rather than relying on mock omissions.
5. Add runtime validation at the repository boundary. Use a schema library only if the team accepts the dependency; otherwise keep validation in a small adapter module.
6. Add fixtures for an empty workspace, active sprint, blocked agent, completed sprint, and partially accepted artifact.

**Exit criteria:** Both views compile against canonical domain types; no shared domain type is imported from a mock-data file.

### Phase 3: Introduce Shared Read State

**Objective:** Make both views read the same in-memory workspace state.

Tasks:

1. Add a `WorkspaceStore` with immutable state transitions.
2. Add selectors for:
   - active phase;
   - active agents;
   - selected agent;
   - selected meet;
   - transcript for the selected meet;
   - artifact acceptance ratio;
   - current metrics;
   - delegation graph.
3. Add `WorkspaceProvider` above both views, below the shell.
4. Replace GenUI local entity state with selectors and store actions.
5. Replace Control Plane `ScrumContext` data state with the shared provider. Preserve Control Plane tab/navigation state locally if it is purely presentational.
6. Keep selection and open-modal state separate from server-owned workspace state.

**Exit criteria:** Switching views does not create two workspace stores; a state change is visible in both views after switching; store transitions are pure and tested.

### Phase 4: Put Mock Behavior Behind the Repository

**Objective:** Preserve the current demo without hard-coding mock behavior into components.

Tasks:

1. Implement `MockWorkspaceRepository` using existing fixtures.
2. Move simulation timers out of view components and into the mock repository or a dedicated simulation adapter.
3. Ensure only one simulation loop exists for the mounted workspace.
4. Convert UI actions into `WorkspaceCommand` values.
5. Make command results and generated events pass through the same reducer as future backend events.
6. Add reset/seed controls for deterministic tests.

**Exit criteria:** The UI has no direct dependency on `INITIAL_*` data or simulation timers; mock mode still reproduces the current demo.

### Phase 5: Add Transport Adapters

**Objective:** Make a real backend replace the mock without UI changes.

Tasks:

1. Implement `HttpWorkspaceRepository.getSnapshot` with an injectable base URL.
2. Implement command execution with typed request/response mapping.
3. Implement a single workspace event connection.
4. Prefer SSE for server-to-browser live updates unless the product requires high-frequency bidirectional messaging. Use WebSockets only behind the same `subscribe` contract.
5. Handle reconnect, cleanup, duplicate events, ordering, stale versions, and authorization failures.
6. Add request cancellation and timeout handling.
7. Keep credentials and API URLs in runtime configuration; never hard-code secrets in the client.

Potential transport shape:

```text
GET  /workspace/{id}/snapshot
POST /workspace/{id}/commands
GET  /workspace/{id}/events
```

These are proposed shapes only. Align them with the backend's actual contract and document the final API using OpenAPI.

**Exit criteria:** Swapping `MockWorkspaceRepository` for `HttpWorkspaceRepository` requires configuration, not component edits.

### Phase 6: Backend Contract and Generated Client

**Objective:** Prevent frontend/backend drift.

Tasks:

1. Agree on the API contract before implementation coupling.
2. Add an OpenAPI document or consume the backend's authoritative OpenAPI document.
3. Generate request/response types or a typed client in a reproducible script.
4. Add contract tests against representative snapshots, commands, errors, and events.
5. Version breaking changes explicitly.
6. Document authentication, workspace authorization, pagination, rate limits, and event retention/replay behavior.

**Exit criteria:** CI detects incompatible API schema changes before merge; generated artifacts are reproducible and not hand-edited.

### Phase 7: Remove Prototype Coupling

**Objective:** Make the codebase independently understandable and maintainable.

Tasks:

1. Move the Control Plane view into the host source tree or package it as a local workspace module.
2. Remove filesystem-relative imports across app boundaries.
3. Consolidate dependencies and remove duplicate app configuration.
4. Keep view-specific CSS scoped or clearly owned.
5. Remove mock-only simulation logic from production paths.
6. Add error, loading, empty, disconnected, permission-denied, and stale-data states.
7. Add observability hooks for command failures and event stream health.

 **Exit criteria:** The frontend can be built, tested, and deployed from one project root without sibling-project knowledge.

> **Satisfied by `migration_planv2.md` (Phases 2–3).** The sibling project is
> deleted; the view lives at `src/views/control-plane/`; one install, one
> React, one HTML entry. Items 5–7 were already satisfied in the v1 slice
> (centralized simulation, full resilience states, command/stream
> observability via provider state).

## Testing Strategy

### Unit Tests

Test pure logic without rendering:

- domain event reducer applies each event correctly;
- duplicate `eventId` is ignored;
- stale event versions do not overwrite newer state;
- selectors derive correct metrics and active entities;
- commands validate required fields;
- immutable updates do not mutate previous snapshots;
- timestamp and phase transitions are deterministic.

### Repository Contract Tests

Run the same contract suite against both repositories:

- mock snapshot loads;
- HTTP snapshot maps into canonical state;
- command success maps into events/state;
- command validation errors are surfaced consistently;
- subscription cleanup closes the connection;
- reconnect behavior does not duplicate events;
- malformed events are rejected without corrupting state.

### Component Tests

Verify both views consume shared state:

- GenUI renders the canonical active phase;
- Control Plane renders the same agent and message data;
- a reassignment appears in both views after the store updates;
- a new message appears in both transcript surfaces;
- mode switching does not reset workspace state;
- presentational tab selection remains independent from workspace data.

### Integration Tests

Use a deterministic mock repository:

1. Load the shell.
2. Confirm GenUI is selected.
3. Start a sprint.
4. Emit an agent update and a message event.
5. Switch to Control Plane.
6. Verify the same agent and message are visible.
7. Execute an SME directive.
8. Switch back to GenUI.
9. Verify the directive and phase state remain consistent.

### Browser and Visual Tests

At minimum test:

- desktop viewport with all Control Plane rails;
- narrow embedded viewport with responsive rail behavior;
- GenUI at kickoff and later phases;
- Control Plane overview, canvas, meet, artifacts, and timeline tabs;
- reduced-motion preference;
- keyboard navigation for the top-level mode tabs.

Use screenshot comparison only after behavior assertions pass. Visual tests should detect layout regressions, not define the data contract.

### Failure and Resilience Tests

Verify:

- initial snapshot loading;
- empty workspace;
- API 401/403/404/409/429/500 responses;
- event stream disconnect and reconnect;
- duplicate and out-of-order events;
- command timeout and retry policy;
- stale selected agent after a refresh;
- partial artifact data;
- backend unavailable while cached state remains visible.

## Proposed Scripts

Add scripts incrementally to `package.json`:

```json
{
  "lint": "tsc --noEmit",
  "test": "vitest run",
  "test:watch": "vitest",
  "test:coverage": "vitest run --coverage",
  "test:e2e": "playwright test",
  "build": "vite build"
}
```

Do not add all tooling in one large change. First add unit/component tests, then browser tests when the shell boundary is stable.

## Configuration Requirements

Use a typed configuration module with safe defaults:

```ts
interface AppConfig {
  apiBaseUrl: string;
  workspaceId: string;
  transport: 'mock' | 'http-sse' | 'http-websocket';
  enableSimulation: boolean;
}
```

Rules:

- Public frontend variables may configure URLs and feature flags only.
- Secrets must remain on the server or in the deployment platform's secret store.
- Configuration should be injected into repositories, not read directly by view components.
- The mock repository must remain the default for local UI development until the backend is available.

## Migration Rules

- One behavior change per pull request where practical.
- Do not redesign the UI during the state migration.
- Do not move a component and change its behavior in the same step unless required by the boundary.
- Prefer adapters over mass renaming.
- Never mutate mock or server snapshots in place.
- Never let a component open its own live event connection.
- Preserve public identifiers and event names once backend integration begins.
- Keep migrations reversible until the mock and HTTP repositories pass the same contract suite.

## Definition of Done

The migration is complete when:

- Both views use one `WorkspaceProvider` and one canonical domain model.
- The UI shell only selects views and provides shared providers.
- No view imports `INITIAL_*` data directly.
- No view directly calls browser network APIs.
- Mock and HTTP repositories satisfy the same interface and tests.
- A single event stream updates both views consistently.
- Commands are typed, observable, and handled through the repository boundary.
- Loading, empty, error, disconnected, and permission states exist.
- `npm run lint`, `npm run test`, `npm run build`, and browser smoke tests pass.
- Desktop and narrow viewport screenshots show no regression from the current approved UI.
- The frontend can be configured for another backend implementation without changing view components.

## Recommended First Implementation Slice

Start with Phase 0 and the smallest Phase 3 slice:

1. Add Vitest and a test command.
2. Fix the in-place `prData` mutation.
3. Add canonical `WorkspaceSnapshot`, `WorkspaceEvent`, and `WorkspaceCommand` types.
4. Add a reducer with one event: `message.created`.
5. Add one shared provider exposing the current snapshot.
6. Move one Control Plane read surface and one GenUI read surface to that provider.
7. Add the cross-view integration test.
8. Only then migrate the remaining entities and commands.

This proves the architecture with a narrow, reversible change before moving the entire UI.
