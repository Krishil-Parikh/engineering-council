# Frontend Migration Plan v2 — Single-Project Merge

## 1. Goal

Collapse the two frontend projects into **one runnable project, one HTML entry, one
`node_modules`, one config surface** — while keeping the two views (GenUI, Control Plane),
the canonical domain model, and the repository boundary exactly as `migrationplan.md`
established them.

End state:

- `frontend/agentic-scrum-control-plane` is the only project. It builds, tests, lints,
  and deploys from its own root with zero knowledge of any sibling directory.
- The Control Plane view lives in the host tree as a view module, not a second app.
- Views, state, repositories, and transport keep the dependency direction from v1.
- Swapping mock → real backend stays a configuration change plus a transport adapter,
  with a written contract the backend team can build against.
- Each phase below leaves the app runnable, tested, and reversible.

Non-goals (explicitly out of scope):

- No UI redesign. Visual changes are limited to restoring already-intended styling
  (Phase 1) and are reviewed via screenshots.
- No backend implementation. v2 prepares the seam (factory, config, contract docs);
  it does not build the server.
- No dependency version upgrades. Upgrades (Tailwind/Vite majors especially) can
  shift build output and pixels in ways gates catch but cannot attribute to the
  move — they get a dedicated, baseline-gated chore phase later, on the smaller
  surface this migration leaves behind.
- In scope, by contrast: pruning the five provably-dead manifest entries
  (`express`, `@google/genai`, `dotenv`, `tsx`, `@types/express`) in Phase 3.
  Verified: zero importers in `src`, no `server.js` exists. `@types/node` stays
  (the Vite config needs it). Rationale: removal is provable-safe (gates prove
  it completely), it rides the already-paid-for fresh install, and a manifest
  advertising a server + Gemini in a pure frontend misdescribes the architecture
  to the backend team.
- No test-framework changes. Vitest + Testing Library + Playwright stay.

## 2. Principles carried over from `migrationplan.md`

These still bind. They are summarized here; the v1 document remains authoritative
for rationale.

- Dependency direction is law:
  `views -> state/domain`, `state -> repository interface`,
  `repositories -> transport/configuration`, `transport -> browser/network APIs`.
- Views never call `fetch`, `EventSource`, or `WebSocket`, and never import
  repository seed data. Seed data is owned by the adapter/repository layer;
  static presentational copy is owned by the view that renders it.
- One behavior change per step where practical. Never move files and change
  behavior in the same commit unless the boundary forces it.
- Never mutate snapshots in place. Never let a component open its own event
  connection. One simulation loop, owned by the shell.
- Every phase is reversible from git and ends with all four gates green.
- The mock repository stays the default until a backend exists. Secrets never
  enter the client; only URLs and feature flags are configurable.

## 3. Starting inventory (verified, not assumed)

### 3.1 The two projects

| | Host (`agentic-scrum-control-plane`) | Sibling (`the-deck-—-agentic-scrum-control-plane`) |
|---|---|---|
| `package.json` scripts | dev, build, preview, clean, **lint, test, test:watch, test:e2e** | dev, build, preview, clean, lint (**no test runner**) |
| Entry | `index.html` → `src/main.tsx` → `src/App.tsx` (built + served) | `index.html` → `src/main.tsx` (**never built or served**) |
| Tests | 58 vitest + 4 Playwright, green | none |
| Deps | superset (adds `framer-motion`, `recharts`, test toolchain) | subset of host's |
| `node_modules` | real, used | duplicate `react`/`react-dom`/`motion` (untracked by git, ignored) |

### 3.2 What is live vs dead in the sibling

- **Live** (bundled into the host build via direct source imports): `src/App.tsx`,
  `src/context/ScrumContext.tsx`, all of `src/components/**`, `src/types.ts`,
  `src/data/mockData.ts` (repository seed only).
- **Dead** (nothing references them): `index.html`, `src/main.tsx`, `src/index.css`,
  `vite.config.ts`, `tsconfig.json`, `package.json`, `bun.lock`, `metadata.json`,
  `README.md`, `node_modules/`, `package-lock.json` if present.

### 3.3 The complete cross-boundary import map

Only **four files** cross the project boundary. Everything else is internal and
survives the move untouched.

Host → sibling (become in-repo relative imports in Phase 2):

- `src/views/ControlPlaneView/ControlPlaneView.tsx:2` imports sibling `src/App`.
- `src/adapters/control-plane/toWorkspaceSnapshot.ts:1` imports sibling
  `src/data/mockData`.

Sibling → host (become in-repo relative imports in Phase 2):

- Sibling `src/App.tsx:15-16` imports `domain/types`, `domain/commands`.
- Sibling `src/context/ScrumContext.tsx:3-5` imports the same.

No sibling component imports sibling `data/mockData` or sibling `main.tsx`.
No host file imports sibling `index.css` (verified: the sibling cascade is dead
weight — see 3.4).

### 3.4 CSS findings (silent-breakage risks, read before Phase 1)

- Host `src/index.css:2` contains
  `@source "../../the-deck-—-agentic-scrum-control-plane/src"`.
  Tailwind v4 scans the sibling tree through this line. **If the move happens
  without updating it, utilities used only by Control Plane components get
  purged and the view breaks silently.** The `@source` update and the move must
  land together (Phase 2), with screenshots as the gate.
- Sibling-only utilities/keyframes with **no host equivalent**: `.mono`,
  `.glass-panel`, `.tabular-nums`, `.live-pulse` + `liveGlowPulse`,
  `.edge-pulse` + `edgeDash`, `var(--font-mono)`, font smoothing on `body`.
  Control Plane components use them (e.g. `mono` everywhere,
  `var(--font-mono)` in the canvas). Today they silently no-op. Phase 1 merges
  them into the host cascade, which *restores* intended styling — the one
  sanctioned visual change in this plan, reviewed pixel-by-pixel.
- Sibling `:root`/`body` rules and `user-select: none` are **not** moved.
  The host cascade owns tokens and page defaults; moving a second `:root`
  would fork the design system on day one.
- Fonts: sibling `index.html` loads Inter + JetBrains Mono; host loads
  Plus Jakarta Sans + JetBrains Mono. **Decision: keep the host pairing.**
  Components referencing `var(--font-mono)` resolve to JetBrains Mono via the
  merged token. No Inter. (Rationale: one pairing, zero new network fonts,
  current screenshots already approved on it.)

## 4. Target architecture

```text
frontend/agentic-scrum-control-plane/   # the only project
  index.html                            # the only HTML entry
  package.json                          # the only manifest (host's, kept whole)
  vite.config.ts                        # single config (react alias removed, Phase 3)
  playwright.config.ts / e2e/           # unchanged
  .env.example                          # extended with backend vars (Phase 5)
  src/
    main.tsx / index.css / App.tsx      # composition root (unchanged shape)
    app/                                # WorkspaceShell, ViewRegistry consumer, config
    domain/ state/ repositories/        # untouched boundaries
    adapters/                           # seed + simulation + validation (unchanged)
    views/
      GenUIView/                        # GenUI view (unchanged)
      control-plane/                    # MOVED sibling src, layout preserved:
        ControlPlaneView.tsx            # renamed from App.tsx (re-export shim compatible)
        components/ context/ types.ts data/
    test/                               # setup + fixtures (unchanged)
  docs/
    backend-contract.md                 # NEW (Phase 5): transport + event/command catalog
  contracts/
    openapi.workspace.stub.yaml        # NEW (Phase 5): machine-readable stub for backend team
```

Ownership rules after the merge:

- `src/views/control-plane/` owns view code and view-local types only. It may
  import from `domain/`, `state/`, and its own subtree — never from
  `repositories/` internals, never `fetch`/`EventSource`.
- `src/views/control-plane/data/mockData.ts` stays exactly where it lands and is
  documented as **repository seed**, consumed solely by
  `src/adapters/control-plane/toWorkspaceSnapshot.ts`. No view file imports it
  (enforced by gate, Phase 2).
- `src/repositories/` remains the only HTTP-aware layer. Phase 5 adds a
  `createRepositoryFromConfig()` factory so backend swap is one call site.
- Static GenUI reference docs stay in `src/views/GenUIView/referenceArtifacts.ts`.

## 5. Phase plan

Conventions used below:

- **Gate** = all four must pass before the phase is done:
  `npm run lint`, `npm run test`, `npm run build`, `npm run test:e2e`.
- **Grep gates** are exact commands that must print the stated result.
- **Rollback** = `git reset --hard` to the phase-start commit (work is committed
  per phase; see 5.0). Nothing below requires uncommitted work to survive.

### Phase 0 — Freeze and baseline

Objective: prove the starting point is green and record it, so every later
phase has something to be "no worse than".

Operations:

1. `git status` clean. No other branches touching `frontend/`.
2. Run the full gate once and record counts:
   `npm run lint`, `npm run test`, `npm run build`, `npm run test:e2e`.
3. Confirm the pre-existing screenshot set `e2e/screenshots/` is current
   (re-run e2e; it re-captures).
4. Record the dependency inventory: `npm ls react react-dom` (expect two
   copies: host + sibling) and `du -sh ../the-deck-—-agentic-scrum-control-plane/node_modules`.
5. Confirm the cross-boundary map in 3.3 is still exact:
   `grep -rn "the-deck" src --include='*.ts' --include='*.tsx'`
   must print exactly the two host files;
   `grep -rn "agentic-scrum-control-plane/src" ../the-deck-—-agentic-scrum-control-plane/src`
   must print exactly the two sibling files.

Exit criteria: gate green; baseline numbers and the two grep outputs pasted
into the phase log (a checklist in the tracking issue, not a code change).

### Phase 1 — CSS decoupling (visual safety before the move)

Objective: make the host cascade self-sufficient so the later deletion of
sibling `index.css` changes zero pixels (beyond restoring the intended
utilities from 3.4).

Operations (host tree only; sibling untouched):

1. Merge into host `src/index.css`: `.mono`, `.glass-panel`,
   `.tabular-nums`, `.live-pulse` + `liveGlowPulse`, `.edge-pulse` +
   `edgeDash`, `--font-mono: 'JetBrains Mono', monospace` in `:root`,
   font-smoothing on `body`. Keep host tokens, scrollbar, and deck-shell
   rules as-is. Do **not** move `:root` wholesale or `user-select: none`.
2. Keep `@source` pointing at the sibling (it still exists).
3. No component or logic changes.

Gates:

- Full gate green.
- `npm run test:e2e` re-captures screenshots; review the four images against
  the Phase 0 baseline. Expected delta: live dots pulse, `mono` text renders
  in JetBrains Mono, canvas edges animate. Any other delta fails the phase.
- Grep gate: sibling `src/index.css` still unreferenced
  (`grep -rn "the-deck.*index.css\|from '.*index.css'" src` → only host's own
  `./index.css` in `main.tsx`).

Rollback: revert the single `index.css` commit.

### Phase 2 — The move (pure relocation + import rewiring)

Objective: one `src` tree. No behavior changes; renames and path edits only.

Operations (single commit for the `git mv`, then path edits — two commits,
reviewable separately):

1. `git mv` verbatim (internal imports survive untouched):
   `../the-deck-—-agentic-scrum-control-plane/src`
   → `src/views/control-plane/`
   Quote the em-dash path; use `--` (see 8.1). This moves 19 source files
   plus the dead `main.tsx`/`index.css` temporarily — they are removed in
   step 3, same phase, separate commit.
2. Delete the moved-but-dead entry points:
   `git rm src/views/control-plane/main.tsx src/views/control-plane/index.css`.
   (Rationale: host `main.tsx`/`index.css` own the entry and cascade.)
3. Rename `src/views/control-plane/App.tsx` →
   `src/views/control-plane/ControlPlaneView.tsx` (default export kept, so
   the shell diff is one import line). Delete the now-redundant
   `src/views/ControlPlaneView/` wrapper directory.
4. Rewire exactly four files:
   - `src/views/control-plane/ControlPlaneView.tsx`: domain imports →
     `../../domain/types`, `../../domain/commands`.
   - `src/views/control-plane/context/ScrumContext.tsx`: same →
     `../../domain/types`, `../../domain/commands`.
   - `src/adapters/control-plane/toWorkspaceSnapshot.ts`: seed import →
     `../../views/control-plane/data/mockData`.
   - `src/app/WorkspaceShell.tsx` (or registry): view import →
     `../views/control-plane/ControlPlaneView`.
5. Update Tailwind scan: host `src/index.css` `@source` →
   `"./views/control-plane"` (same commit as the move — never land one
   without the other).
6. Update `VIEW_REGISTRY` if it referenced the deleted wrapper path.

Gates:

- Full gate green.
- Grep gates (all must hold):
  - Zero references to the old directory name anywhere in the repo source:
    `grep -rn "the-deck" src e2e index.html vite.config.ts playwright.config.ts package.json` → empty.
  - No view file imports repository seed:
    `grep -rn "views/control-plane/data/mockData\|data/mockData" src/views` → empty.
    (Only `src/adapters/control-plane/toWorkspaceSnapshot.ts` may import it.)
  - No view touches network APIs:
    `grep -rn "fetch(\|EventSource\|WebSocket" src/views src/app` → empty.
- Screenshots from e2e reviewed against Phase 1: **zero unintended delta**
  (Phase 1 already absorbed the intended styling restoration).

Rollback: revert the two commits (move + rewiring) in reverse order.

### Phase 3 — Delete the sibling project, prune dead deps, single install

Objective: remove every dead scaffold file and dead manifest entry, and prove
one install suffices.

Operations:

0. Prune the five provably-dead manifest entries from host `package.json`:
   `express`, `@google/genai`, `dotenv`, `tsx`, `@types/express`.
   Keep `@types/node` (Vite config needs it). Proof of deadness (re-run at
   execution time across the whole project, not just `src` — a hidden script
   or config could reference them; must be empty before pruning):
   `grep -rn "@google/genai\|from 'express'\|from \"express\"\|require('express')\|dotenv\|GEMINI_API_KEY\|tsx" --include='*.ts' --include='*.tsx' --include='*.js' --include='*.json' --include='*.yaml' --include='*.md' . --exclude-dir=node_modules --exclude-dir=dist`
   plus confirming no `server.{js,ts}` exists at the project root.
1. Delete from disk (all untracked-or-dead; sibling `node_modules/` is
   git-ignored so this is `rm -rf`, not `git rm`):
   sibling `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`,
   `bun.lock`, `metadata.json`, `README.md`, `node_modules/`,
   `package-lock.json` if present. Then remove the now-empty sibling dir.
2. Simplify host `vite.config.ts`: drop the `react`, `react-dom`, `motion`,
   and `lucide-react` aliases (single copy exists by construction; plain
   resolution applies). Keep `@`, plugins, server, and test blocks.
   Mirror the removal in `tsconfig.json` `paths` for `motion/*` and
   `lucide-react` (keep `@/*`).
3. Fresh-install proof: `rm -rf node_modules package-lock.json &&
   npm install` (allow time), then full gate. Known pre-existing condition:
   stock `npm install` fails on peer resolution (`vite@8` vs vitest's
   peer ranges — predates this migration); use `npm install --legacy-peer-deps`
   and record it. Do not "fix" by upgrading (see Non-goals).

Gates:

- Full gate green **after the fresh install** — this is the phase's point.
- `npm ls react` shows exactly one copy. `ls ../the-deck*` fails (gone).
- Prune proof: `npm ls express @google/genai dotenv tsx` errors (not installed);
  the pre-prune grep is still empty on the final tree.
- `tsc` proves alias removal broke nothing (it type-checks resolution too).
- e2e green + screenshots unchanged vs Phase 2. Note: the first e2e run on
  a fresh `node_modules` may time out while Vite cold-optimizes dependencies;
  a rerun with a warm cache is the valid gate (verify a rerun passes rather
  than debugging a cold-cache timeout as a code break).

Rollback: restore the sibling dir from git (`git checkout -- <dir>` covers
tracked files; `node_modules` was never tracked — reinstall is the fix, not
rollback), restore the manifest entries, and revert the config commit.

### Phase 4 — Lazy-split the views (bundle budget)

Objective: one HTML, two code chunks. GenUI paints without the Control Plane
graph code.

Operations:

1. `React.lazy()` the Control Plane component in `viewRegistry.ts`
   (keep the `VIEW_REGISTRY` shape; type becomes
   `React.LazyExoticComponent`). Wrap `ActiveView` in `WorkspaceShell` with
   `<Suspense fallback>` reusing the existing loading state copy.
2. No route, URL, or state changes. GenUI chunk must not import
   control-plane modules (the boundary already guarantees this; the build
   proves it).

Gates:

- Full gate green.
- `npm run build` output shows a separate control-plane chunk besides the
  entry chunk (paste chunk list into the phase log). Entry chunk smaller
  than the pre-split baseline from Phase 0.
- e2e green, including mode-switch and keyboard tests (these exercise the
  lazy boundary, fallback included).

Rollback: revert the registry + shell commit.

### Phase 5 — Backend seam (config, factory, contract)

Objective: make "point at a real backend" a documented, typed, boring
operation. No UI changes in this phase.

Operations:

1. `createRepositoryFromConfig(config)` in `src/repositories/`; `App.tsx`
   uses it (replacing the inline ternary). Mock stays default.
2. `.env.example` documents every supported variable:
   `VITE_TRANSPORT`, `VITE_API_BASE_URL`, `VITE_WORKSPACE_ID`,
   `VITE_ENABLE_SIMULATION` (plus the existing AI-Studio entries, untouched).
3. New `docs/backend-contract.md`: transport shape
   (`GET /workspace/{id}/snapshot`, `POST /workspace/{id}/commands`,
   `GET /workspace/{id}/events`), event catalog with `eventId`/`version`
   idempotency rules, command catalog with validation errors, error-code
   conventions (401/403/404/409/429/5xx → UI states), auth notes
   (tokens live server-side; client sends no secrets), pagination/retention
   marked TBD for the backend team.
4. New `contracts/openapi.workspace.stub.yaml`: machine-readable stub of the
   above (stub, not a full spec — suffices for backend-team validation and
   future codegen).
5. Backend bring-up checklist in the same doc: run contract suite against a
   staging backend, flip `VITE_TRANSPORT`, keep mock green in CI.

Gates:

- Full gate green (factory covered by existing + one new unit test asserting
  mock-default and http selection).
- Contract suite (`workspaceRepository.contract.test.ts`) green — the same
  suite the backend must eventually satisfy.
- Docs review: contract doc statements match `HttpWorkspaceRepository` and
  `mapSnapshotHttpError` behavior line-for-line (reviewer checks, not tests).

Rollback: revert (docs + factory are additive; zero UI coupling).

### Phase 6 — Sign-off

Objective: close v2 the way v1 closed — evidence, not adjectives.

1. Full gate, clean tree, screenshots reviewed one last time.
2. Tick the Definition of Done (section 9) item by item with pointers
   (test names, chunk list, grep outputs).
3. Update `migrationplan.md`: mark Phase 7 exit criteria satisfied, fold this
   document's outcome into Implementation Status.
4. Record follow-ups only (no scope creep): express/genai dep hygiene,
   screenshot-diff CI, reduced-motion audit.

## 6. Master test matrix

Every phase runs the full gate; the table shows what each phase *additionally*
must prove. Counts below are current baselines — update them in Phase 0 and
treat any drop as a failure.

| Phase | `lint` | `test` (vitest) | `build` | `test:e2e` | Extra proof |
|---|---|---|---|---|---|
| 0 baseline | pass | 58 pass | pass, note chunk list | 4 pass, captures baseline | grep map exact (3.3); `npm ls react` = 2 copies |
| 1 CSS | pass | 58 pass | pass | 4 pass | screenshots: only intended deltas (pulse, mono, edges) |
| 2 move | pass | 58 pass | pass | 4 pass | zero old-dirname refs; no view→seed imports; no view network APIs; screenshots pixel-stable vs Phase 1 |
| 3 delete | pass | 58 pass | pass | 4 pass | after **fresh** `npm install`; `npm ls react` = 1 copy; sibling dir gone; pruned deps absent (`npm ls` errors) with pre-prune grep still empty |
| 4 lazy | pass | 58 pass (+1 factory-adjacent if added) | pass, **split chunks listed** | 4 pass (exercises fallback) | entry chunk smaller than Phase 0 |
| 5 seam | pass | 59 pass (factory test) | pass | 4 pass | contract suite green; doc↔code consistency review |
| 6 sign-off | pass | all pass | pass | 4 pass | DoD ticked with evidence |

Failure policy: any red gate stops the phase. Fix forward in the phase; if
the fix touches another phase's files, re-run that phase's gates too.

## 7. Backend-integration readiness checklist

(What "easy to connect later" concretely means when v2 lands.)

- [ ] One repository factory; transport chosen by `VITE_TRANSPORT` only.
- [ ] Views contain zero transport knowledge (grep gate, Phase 2, kept ever since).
- [ ] `docs/backend-contract.md` + `contracts/openapi.workspace.stub.yaml` exist
      and match the HTTP adapter's behavior.
- [ ] `.env.example` documents all four `VITE_*` variables.
- [ ] Contract suite passes against mock; same suite is runnable against HTTP
      (already true — extend to staging backend at bring-up).
- [ ] Error taxonomy mapped end-to-end: HTTP status → repository error →
      provider status → UI banner (all covered by `WorkspaceShell.states` tests).
- [ ] Mock remains default; no backend required for any gate.

## 8. Risks and mitigations

1. **Em-dash directory name** (`the-deck-—-…`). Shells and some tools mangle
   it. Mitigation: always quote the path, use `git mv -- "old" "new"`,
   verify with `git status` immediately. The name disappears from the repo in
   Phase 2 — this is the last time anyone types it.
2. **Tailwind purge after the move.** Mitigation: `@source` update lands in
   the same commit as the move; screenshots are the gate, not eyeballing.
3. **Alias removal (Phase 3) hiding a second copy.** Mitigation: `npm ls react`
   single-copy proof plus `tsc`, which resolves the same graph the bundler uses.
4. **Inter font drop.** Sibling components never loaded it in the merged app
   anyway (sibling `index.html` is dead); host pairing is the approved look.
   If a reviewer spots a glyph regression in screenshots, Phase 1 is where it
   gets caught.
5. **Bundle-size creep unnoticed.** Mitigation: Phase 0 records the chunk list;
   Phase 4 requires it to split and shrink.
6. **Solo-developer drift.** Mitigation: commit per phase, green gates per
   phase, and this document as the checklist — no phase starts red.

## 9. Definition of Done (v2)

- [ ] `frontend/` contains exactly one frontend project; no sibling directory,
      no second manifest/config/entry/lockfile.
- [ ] One `npm install` from the host root; `npm ls react` shows one copy.
- [ ] Manifest contains no provably-unused entries (the five pruned in Phase 3;
      `@types/node` kept deliberately).
- [ ] `npm run lint`, `npm run test`, `npm run build`, `npm run test:e2e`
      all green on the final tree.
- [ ] Zero references to the old directory name in tracked files.
- [ ] Dependency direction and all v1 DoD view rules still hold
      (re-verified by the Phase 2 grep gates on the final tree).
- [ ] GenUI and Control Plane render from one provider, one snapshot, one
      event stream (existing cross-view tests, still green).
- [ ] Build emits separate view chunks; entry smaller than the v1 baseline.
- [ ] Repository factory + documented env + contract doc/stub exist; mock
      still default; contract suite green.
- [ ] Desktop + narrow screenshots for both modes reviewed, no unintended
      delta from the v1 baseline set.
- [ ] `migrationplan.md` Phase 7 marked complete with a pointer to this document.

## Appendix A — Command cheat-sheet

```bash
# from frontend/agentic-scrum-control-plane
npm run lint && npm run test && npm run build && npm run test:e2e

# cross-boundary map (Phase 0 + Phase 2 gates)
grep -rn "the-deck" src e2e index.html vite.config.ts playwright.config.ts package.json
grep -rn "agentic-scrum-control-plane/src" "../the-deck-—-agentic-scrum-control-plane/src"

# view-purity gates (Phase 2+, keep forever)
grep -rn "views/control-plane/data/mockData\|data/mockData" src/views
grep -rn "fetch(\|EventSource\|WebSocket" src/views src/app

# prune proof (Phase 3: must be empty before pruning, stays empty after)
grep -rn "@google/genai\|from 'express'\|from \"express\"\|dotenv\|GEMINI_API_KEY" src
ls server.js server.ts 2>/dev/null && echo PRUNE-BLOCKED || echo PRUNE-CLEAR

# single-copy proof (Phase 3+)
npm ls react

# the move (Phase 2 — quote, verify, then edit)
git mv -- "../the-deck-—-agentic-scrum-control-plane/src" "src/views/control-plane"
git status --short
```

## Appendix B — Move inventory

Sibling `src/` = 19 source files + `index.css`, all moving in Phase 2:

- `App.tsx` → `views/control-plane/ControlPlaneView.tsx` (rename, export kept)
- `context/ScrumContext.tsx` (1 of 4 rewired files)
- `components/` × 14 (TabRail, LeftRail, RightInspector, BottomStrip, TopBar,
  OverviewTab, CanvasTab, MeetTab, ArtifactsTab, TimelineTab, MiniCanvas,
  DelegationCanvas, SmeInterventionModal, Odometer) — verbatim
- `types.ts`, `data/mockData.ts` — verbatim (seed ownership documented)
- `main.tsx`, `index.css` — moved then deleted (dead entry/cascade)

Deleted without moving (Phase 3): sibling `package.json`, `vite.config.ts`,
`tsconfig.json`, `index.html`, `bun.lock`, `metadata.json`, `README.md`,
untracked `node_modules/`.

Rewired (4 files, Phase 2 step 4): sibling `ControlPlaneView.tsx`,
`context/ScrumContext.tsx`, host `adapters/control-plane/toWorkspaceSnapshot.ts`,
shell/registry import.
