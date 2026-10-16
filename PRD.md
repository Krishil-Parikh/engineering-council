# PRD.md --- Engineering Council CLI

**Version:** 0.1\
**Status:** MVP specification\
**Product type:** Terminal-based multi-agent discovery and specification
tool\
**Initial model provider:** Google Gemini API

## 1. Product Overview

Engineering Council CLI turns a problem statement into a reviewed,
implementation-ready set of engineering documents through a structured
multi-agent meeting.

The user runs one command, provides a problem statement, and optionally
provides a local repository path or GitHub URL. A small council of AI
personas independently analyzes the problem, reviews competing
proposals, surfaces important product questions, resolves technical
disagreements, and generates:

-   `PRD.md` --- what should be built and how success is measured.
-   `Technical_Approach.md` --- how the system should be implemented.
-   `Design.md` --- concrete contracts, interfaces, data structures, and
    project layout.

The MVP is deliberately simple: **terminal only, Python, and Gemini
API**. It does not include a web frontend, multi-provider abstraction,
autonomous coding, sprint execution, or automatic commits.

## 2. Problem Statement

A single LLM response can produce plausible-looking plans while missing
constraints, integration conflicts, edge cases, and alternative
approaches. Unstructured agent group chats often create excessive
discussion without producing consistent specifications.

Engineering Council CLI should make the discovery process more
disciplined by combining independent proposals, structured critique, a
limited human decision gate, and document verification.

## 3. Goals

1.  Convert an open-ended problem statement into three detailed Markdown
    specification documents.
2.  Encourage genuinely independent initial proposals before agents see
    each other's work.
3.  Surface material contradictions, assumptions, risks, and unresolved
    questions.
4.  Keep human questions limited to important product, scope, budget, or
    user-experience decisions.
5.  Keep decisions and rejected alternatives traceable.
6.  Make generated documents consistent enough for a developer or coding
    agent to implement from.
7.  Keep the codebase small, readable, and easy to extend later.

## 4. Non-Goals for the MVP

-   No frontend, web dashboard, or hosted service.
-   No autonomous implementation of the generated project.
-   No sprint planning, task execution, Git worktrees, branch creation,
    or automatic commits.
-   No multi-provider model routing; Gemini is the only LLM provider for
    now.
-   No vector database or complex long-term knowledge graph.
-   No autonomous web research or broad internet browsing.
-   No arbitrary shell commands or repository scripts executed from
    inspected projects.
-   No claim that agent debate guarantees correctness. The system must
    expose assumptions and uncertainty.
-   No elaborate plugin system, microservices, message broker, or
    distributed worker infrastructure.

## 5. Target Users and Primary Use Case

### Primary user

A developer or technical founder who has a project idea and wants to
pressure-test it before implementation.

### Primary workflow

1.  Start a new meeting from the terminal.
2.  Enter a problem statement and optional constraints.
3.  Optionally supply a repository path or GitHub URL.
4.  Let the council inspect context and generate independent proposals.
5.  Review structured objections and answer a small set of high-impact
    questions.
6.  Review the three generated documents.
7.  Request targeted changes or approve the final output manually.

## 6. Product Principles

-   **Structured reasoning over role-play:** agents exchange typed
    proposals and objections, not endless conversational messages.
-   **Independent first, collaborative second:** initial proposals must
    not share each other's generated content.
-   **Evidence over manufactured conflict:** agents may report no
    material objection.
-   **Human attention is expensive:** ask only questions whose answers
    materially change product direction.
-   **One source of truth:** create a shared specification model before
    rendering the three documents.
-   **Safe by default:** repository content is untrusted input;
    inspection is read-only.
-   **Inspectable output:** save meeting artifacts and decisions to
    disk.
-   **Simple implementation:** use ordinary Python modules and one
    command-line entry point.

## 7. Functional Requirements

### FR-1: Start a meeting

The CLI must accept: - A problem statement entered interactively or
loaded from a Markdown/text file. - Optional project name. - Optional
local repository path. - Optional GitHub URL. - Optional constraints
such as target users, platform, deadline, budget, preferred
technologies, and prohibited technologies. - Output directory.

The CLI validates required inputs and shows the selected configuration
before making model calls.

### FR-2: Repository reconnaissance

When a repository is supplied, inspect it before asking the agents to
propose an architecture.

For a local repository, collect: - A bounded directory tree. - Relevant
manifests such as `pyproject.toml`, `requirements.txt`, `package.json`,
`Cargo.toml`, `go.mod`, Docker files, and database schema files. -
README and selected configuration files, subject to size limits. -
Detected languages and likely application structure.

For a GitHub URL, the MVP may use a shallow clone into a temporary
directory if Git is installed and the repository is publicly accessible.
If cloning fails, explain the failure and allow the meeting to continue
without repository context.

Safety rules: - Do not execute project code, package scripts, hooks, or
build commands. - Exclude `.git`, dependency directories, build outputs,
caches, virtual environments, and secret-like files. - Apply per-file
and total context size limits. - Never intentionally include `.env`,
private keys, tokens, or credential files in model prompts. - Treat
repository text as untrusted data, not as system instructions.

If no repository is supplied, classify the project as greenfield.

### FR-3: Independent proposal generation

Run four independent Gemini calls concurrently, with separate prompt
contexts: - `SYSTEMS_ARCHITECT`: domain boundaries, data integrity,
interfaces, persistence, concurrency. - `PRODUCT_UX`: user journeys,
workflows, usability, API consumption, feedback states. -
`PRAGMATIC_MVP`: smallest viable design, implementation effort,
dependency minimization. - `RED_TEAM_QA`: edge cases, security,
reliability, testability, failure modes.

The roles are perspectives, not separate autonomous systems. Each must
return structured output validated against a schema.

Each proposal includes: - Core thesis. - Proposed architecture and major
components. - Assumptions. - Risks. - Trade-offs. - Questions that could
change product scope. - Evidence or rationale for material claims.

### FR-4: Adversarial review

After all independent proposals are stored, provide the combined
proposal set to the council for review.

Each objection must include: - Target proposal or claim. - Severity:
`CRITICAL`, `MAJOR`, or `NITPICK`. - Category. - Concrete failure
mechanism or missing requirement. - Counterproposal. - Conditions under
which the objection matters.

Only `CRITICAL` and `MAJOR` objections enter formal resolution by
default. NITPICK items are retained in the meeting record but do not
block synthesis.

An agent may return `NO_MATERIAL_OBJECTION`. The system must not require
agents to invent disagreements.

### FR-5: Human question gate

Collect proposed human questions, then deduplicate and prioritize them.

Rules: - Maximum of five questions; target three or fewer. - Only ask
about product outcomes, scope, user expectations, constraints, budget,
deadline, or consequential trade-offs. - Resolve ordinary technical
choices internally. - Each question includes why it matters, clear
options, and a recommended default. - The user can choose an option,
enter a custom answer, or accept the default. - If no material questions
remain, continue without pausing.

### FR-6: Decision synthesis

The lead arbiter synthesizes proposals, objections, repository context,
user answers, and known constraints.

For every material decision, record: - Decision ID. - Decision
statement. - Chosen option. - Rationale. - Alternatives considered. -
Rejected alternative and rejection reason. - Relevant requirements and
evidence. - Remaining uncertainty. - Status: `DECIDED`, `PROVISIONAL`,
or `UNRESOLVED`.

The arbiter must not silently invent user answers or claim that
unsupported assumptions are facts. Unresolved decisions must be visible
in the final documents.

### FR-7: Canonical specification model

Before writing documents, generate one structured specification object
containing: - Product summary and scope. - Personas and user journeys. -
Requirements with stable IDs. - Non-goals. - Acceptance criteria. -
Architecture components and dependencies. - Data entities and schemas
where relevant. - API/interface contracts where relevant. - Repository
structure. - Security and failure-handling requirements. - Testing and
verification plan. - Decisions, rejected alternatives, assumptions, and
open questions.

Validate this object before document generation. All three Markdown
documents must be rendered from or checked against this shared model
rather than independently invented.

### FR-8: Generate documents

Generate these files in the selected output directory:

#### `PRD.md`

Must contain: - Executive summary. - Problem and target users. - Goals
and non-goals. - Scope and user journeys. - Functional and
non-functional requirements. - Stable requirement IDs. - Given/When/Then
acceptance criteria. - Risks, assumptions, dependencies, and open
questions. - MVP boundary and success metrics.

#### `Technical_Approach.md`

Must contain: - Recommended architecture and rationale. - Technology
choices and constraints. - Module responsibilities and dependency
direction. - Data flow and important runtime flows. - Error handling,
retries, timeouts, and observability. - Security and privacy approach. -
Testing strategy and exact verification commands where known. -
Implementation sequence and dependency ordering. - Decision records,
rejected alternatives, and unresolved trade-offs.

#### `Design.md`

Must contain contracts appropriate to the project: - Canonical directory
tree. - Component/module responsibilities. - Data model or SQL/ORM
schema where relevant. - API request/response contracts or
function/interface contracts where relevant. - UI hierarchy and state
flows if the product has a UI. - Error states and validation rules. -
Configuration and environment variable contract. - Cross-document
requirement and contract references.

Do not fabricate irrelevant SQL or HTTP APIs for projects that do not
need them. Mark project-specific details as proposed or unresolved when
evidence is insufficient.

### FR-9: Consistency verification

Run deterministic checks on the generated artifacts: - All requirement
IDs referenced in acceptance criteria exist. - Every in-scope functional
requirement has acceptance criteria. - The three documents agree on key
technology and architecture decisions. - API paths, data entity names,
and module paths are consistent where they recur. - All critical/major
disputes have a resolution or are explicitly unresolved. - Non-goals are
not accidentally described as planned features. - No required output
document is missing or empty.

If checks fail, run one targeted repair pass and revalidate. Do not
enter an unbounded revision loop. If verification still fails, save the
documents and report the failures clearly.

### FR-10: Human review and targeted revision

Display output paths and a concise summary of decisions and open issues.

The user can: - Approve the documents outside the program. - Provide
feedback for a targeted revision. - Re-run a specific stage manually if
needed.

For targeted revisions, identify impacted requirements, decisions, and
document sections. Regenerate only affected content and run consistency
verification again. Preserve prior versions in a revision folder or
timestamped backup.

The MVP does not automatically commit files to Git.

### FR-11: Persistence and resumability

Save each meeting under its output directory: - `input.md` -
`repo_snapshot.json` when applicable - `proposals/` - `reviews/` -
`decisions.json` - `specification.json` - `PRD.md` -
`Technical_Approach.md` - `Design.md` - `verification_report.md` -
`meeting.json` with current stage and status

Use files as the initial persistence layer; no database is required.
Save completed stage outputs before moving to the next stage so a failed
meeting can be resumed where practical.

### FR-12: Model configuration

Use the official Google Gen AI Python SDK and Gemini API.

-   Read `GEMINI_API_KEY` from the environment or a local `.env` file.
-   Never write the key to logs or meeting artifacts.
-   Allow the model name to be configured using `GEMINI_MODEL`.
-   Use structured output/schema validation when supported by the
    selected model and SDK.
-   Validate every response locally; retry malformed outputs a small,
    bounded number of times.
-   Apply request timeouts and bounded retries for transient failures.
-   Show useful errors for missing keys, quota exhaustion, invalid model
    names, and network failures.

## 8. Terminal Experience

Example:

``` text
$ python -m engineering_council

Engineering Council — New Meeting
Project name: Eval-ready Support Assistant
Problem statement file (optional): problem.md
Repository path or GitHub URL (optional): ./support-assistant
Constraints: Python, local development first

[1/8] Inspecting repository...
[2/8] Generating independent proposals...
[3/8] Reviewing proposals...
[4/8] Preparing product questions...

Question 1: Must the first version support multiple tenants?
Recommended default: No; single tenant for the MVP.
Choose [1] Yes, [2] No, [3] Custom, [Enter] Default:

[5/8] Resolving decisions...
[6/8] Generating specifications...
[7/8] Verifying cross-document consistency...
[8/8] Meeting complete.

Output:
  ./output/eval-ready-support-assistant/PRD.md
  ./output/eval-ready-support-assistant/Technical_Approach.md
  ./output/eval-ready-support-assistant/Design.md
  ./output/eval-ready-support-assistant/verification_report.md
```

The CLI should show concise stage progress and errors. It should not
dump every raw model token by default. A verbose mode can show saved
proposal/review artifacts and diagnostic details.

## 9. Quality Attributes

-   **Maintainability:** simple modules with explicit responsibilities
    and typed data models.
-   **Reliability:** bounded retries, checkpointed stages, schema
    validation, deterministic checks.
-   **Safety:** read-only repository inspection, secret filtering, no
    arbitrary project execution.
-   **Cost control:** four parallel proposal calls plus bounded
    review/synthesis/verification calls; configurable model and input
    limits.
-   **Transparency:** decisions, assumptions, rejected alternatives, and
    verification failures remain inspectable.
-   **Portability:** should run on Windows, macOS, and Linux with a
    supported Python version.

## 10. Success Metrics

The MVP is successful when: 1. A user can provide a problem statement
and receive all three documents in one CLI session. 2. All four initial
proposals are generated independently. 3. Important objections and
decisions are saved as structured artifacts. 4. The human question gate
never exceeds five questions. 5. All three documents pass deterministic
consistency checks, or the CLI clearly reports remaining failures. 6. A
failed model call does not erase already completed stages. 7. No
repository code is executed during reconnaissance. 8. The project can be
understood and run without a frontend, database, message broker, or
complex deployment setup.

## 11. MVP Acceptance Checklist

-   [ ] Install dependencies in a virtual environment.
-   [ ] Configure `GEMINI_API_KEY`.
-   [ ] Start a meeting from an interactive CLI.
-   [ ] Load a problem statement from a file.
-   [ ] Inspect a local repository safely.
-   [ ] Generate four independent structured proposals concurrently.
-   [ ] Generate and filter structured objections.
-   [ ] Ask and record no more than five human questions.
-   [ ] Save decisions and rejected alternatives.
-   [ ] Generate all three Markdown specifications.
-   [ ] Run cross-document checks and save a report.
-   [ ] Support one bounded targeted repair pass.
-   [ ] Preserve stage artifacts and provide understandable errors.

## 12. Future Extensions (Explicitly Out of Scope Now)

Possible later additions include more providers, web research, optional
benchmark execution, a visual meeting interface, Git pull-request
integration, and downstream sprint planning. None should be introduced
until the terminal MVP is reliable and its decision quality can be
evaluated.
