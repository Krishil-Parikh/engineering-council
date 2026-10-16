# Technical_Approach.md --- Engineering Council CLI

**Version:** 0.1\
**Status:** MVP implementation plan\
**Primary language:** Python\
**LLM provider:** Google Gemini API\
**Interface:** Terminal only

## 1. Technical Summary

Build a small Python CLI that orchestrates a structured multi-agent
meeting and produces three coherent Markdown documents. Use asynchronous
Gemini calls for independent proposal generation, Pydantic models for
typed outputs, local files for persistence, and deterministic Python
checks for document consistency.

The initial architecture is a **single Python application**, not a
distributed agent platform. Avoid a web server, frontend, database,
queue, vector store, plugin framework, and autonomous coding loop.

## 2. Technology Choices

  -----------------------------------------------------------------------
  Concern                 MVP choice              Reason
  ----------------------- ----------------------- -----------------------
  Language                Python 3.11+            Strong typing ecosystem
                                                  and straightforward
                                                  async I/O

  CLI                     `typer` or              Friendly commands
                          standard-library        without building a UI
                          `argparse`              

  Gemini SDK              `google-genai`          Official Google Gen AI
                                                  SDK

  Schemas                 `pydantic`              Validate model
                                                  responses and internal
                                                  contracts

  Async concurrency       `asyncio`               Run independent
                                                  proposal calls
                                                  concurrently

  Environment             `python-dotenv` plus    Simple local
                          environment variables   configuration

  Markdown output         Standard file I/O and   Keep document
                          Jinja2 only if useful   generation easy to
                                                  inspect

  Testing                 `pytest`                Unit and integration
                                                  tests

  Logging                 Python `logging`        No additional
                                                  observability stack

  Persistence             JSON and Markdown files Easy to inspect, back
                                                  up, and resume

  Git inspection          `git` CLI invoked only  No execution of
                          for clone/list          repository scripts
                          operations, or local    
                          filesystem traversal    
  -----------------------------------------------------------------------

Do not add LangGraph or another orchestration framework in the first
version. The meeting flow is small enough to represent as explicit
Python functions and a stage enum. A graph framework can be reconsidered
if real branching complexity emerges.

## 3. High-Level Flow

``` text
CLI input
   |
   v
Input validation
   |
   v
Repository reconnaissance (optional, read-only)
   |
   v
Four independent proposal calls (async)
   |
   v
Pydantic validation and saved proposal artifacts
   |
   v
Adversarial review calls
   |
   v
Deterministic severity filter + question deduplication
   |
   v
Human answers/defaults
   |
   v
Arbiter synthesis -> decisions + canonical specification JSON
   |
   v
Render PRD.md, Technical_Approach.md, Design.md
   |
   v
Deterministic consistency verification
   |
   +--> one bounded repair pass if needed
   |
   v
Final report and output paths
```

Each stage should be an explicit function with typed input and output.
Persist its result before starting the next stage.

## 4. Simple Directory Structure

``` text
engineering-council/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── src/
│   └── engineering_council/
│       ├── __init__.py
│       ├── cli.py              # CLI arguments and interactive prompts
│       ├── config.py           # Gemini key, model, paths, limits
│       ├── models.py           # Pydantic schemas for every stage
│       ├── prompts.py          # Persona instructions and stage prompts
│       ├── gemini_client.py    # One Gemini adapter, timeout and retry
│       ├── repository.py       # Safe, read-only repo inspection
│       ├── meeting.py          # Stage orchestration and checkpoints
│       ├── questions.py        # Deduplication and human interaction
│       ├── synthesis.py        # Decisions and canonical spec creation
│       ├── documents.py        # Render the three Markdown documents
│       ├── verification.py     # Deterministic consistency checks
│       └── storage.py          # JSON/Markdown persistence
└── tests/
    ├── test_models.py
    ├── test_questions.py
    ├── test_repository.py
    ├── test_documents.py
    └── test_verification.py
```

This is intentionally compact. Do not create separate packages for each
agent or generic abstractions before they are needed. Agent personas can
be prompt definitions and shared schema types. The single Gemini client
is the only model-provider integration.

## 5. Module Responsibilities

### `cli.py`

-   Accept problem statement text/file, project name, optional
    repository, constraints, output directory, and verbose flag.
-   Confirm the selected model and output path.
-   Invoke the meeting orchestrator.
-   Render stage progress and final paths.
-   Convert expected failures into concise terminal messages.

### `config.py`

-   Load `GEMINI_API_KEY` and `GEMINI_MODEL`.
-   Set output path, request timeout, retry limit, context limits, and
    maximum questions.
-   Fail early if the API key is missing.
-   Never print secret values.

### `models.py`

Define Pydantic models for the entire workflow. Prefer enums and bounded
lists where useful.

Suggested types:

``` python
from typing import Literal
from pydantic import BaseModel, Field

Severity = Literal["CRITICAL", "MAJOR", "NITPICK"]

class ComponentProposal(BaseModel):
    name: str
    approach: str
    rationale: str
    assumptions: list[str] = []
    risks: list[str] = []

class AgentProposal(BaseModel):
    agent_id: str
    thesis: str
    components: list[ComponentProposal]
    risks: list[str]
    assumptions: list[str]
    product_questions: list[str] = []

class Dispute(BaseModel):
    source_agent: str
    target_agent: str
    claim: str
    severity: Severity
    category: str
    failure_mechanism: str
    counterproposal: str
    conditions: list[str] = []

class HumanQuestion(BaseModel):
    question: str
    why_it_matters: str
    options: list[str]
    recommended_default: str

class Decision(BaseModel):
    decision_id: str
    statement: str
    chosen_option: str
    rationale: str
    rejected_alternatives: list[str]
    status: Literal["DECIDED", "PROVISIONAL", "UNRESOLVED"]
    remaining_uncertainty: list[str] = []
```

Use `Field(default_factory=list)` rather than mutable list defaults in
production Pydantic models. The snippet is illustrative and should be
corrected accordingly when implemented. Add explicit models for
repository snapshots, requirement records, canonical specification,
verification results, and meeting state. Avoid accepting arbitrary
unvalidated JSON as the final internal representation.

### `prompts.py`

Store prompts as named Python constants or small text files: - Four
independent proposal personas. - Adversarial review. - Question
curation. - Arbiter synthesis. - Specification completion. - Targeted
repair.

Prompts must explicitly distinguish user requirements, repository
observations, model inferences, and unknowns. Repository content must be
quoted or clearly delimited as untrusted data.

### `gemini_client.py`

Implement one small adapter: - Create the Gemini client from the API
key. - Accept a prompt and expected Pydantic schema. - Request
structured output where supported by the chosen model. - Validate
returned content locally. - Apply bounded retries for transient errors
and malformed output. - Use a timeout. - Return typed objects, not raw
strings, to orchestration code.

Keep provider-specific SDK calls in this module. Do not let the rest of
the application depend directly on SDK response types.

### `repository.py`

-   Inspect a local path or optionally clone a GitHub repository into a
    temporary directory.
-   Use allowlisted filenames and size-limited reads for
    manifests/configuration.
-   Exclude common generated folders and secret files.
-   Limit tree depth, total files, and total prompt bytes.
-   Return a `RepoSnapshot` with mode, tree, detected technologies,
    selected file excerpts, and inspection warnings.
-   Never execute inspected code, dependency installers, hooks, tests,
    or build scripts.

For the first implementation, local repository inspection can be
implemented first; public GitHub cloning can be added after local
inspection passes its safety tests.

### `meeting.py`

Orchestrate the meeting in explicit stages: 1. Create output directory
and save inputs. 2. Inspect repository if supplied. 3. Run independent
proposals concurrently. 4. Validate and persist all successful
proposals. 5. Run adversarial review. 6. Filter and persist disputes. 7.
Curate questions and collect human responses. 8. Synthesize decisions
and canonical specification. 9. Render documents. 10. Verify, optionally
repair once, and save final report.

Use `asyncio.gather(..., return_exceptions=True)` or equivalent handling
so one agent failure is visible and does not silently discard all
successful outputs. Define a clear policy: retry a failed call a bounded
number of times, then either continue with an explicit missing-agent
warning if the minimum council quorum is met, or stop before synthesis
if the evidence is insufficient. Never pretend four agents succeeded if
they did not.

### `questions.py`

-   Normalize and deduplicate semantically overlapping questions.
-   Use one bounded Gemini curation call if needed, then enforce the
    maximum in Python.
-   Exclude purely technical implementation choices from the human
    queue.
-   Ask one question at a time in the terminal.
-   Support Enter for the recommended default and custom text.
-   Save each answer and its source.

The deterministic maximum must be applied after model curation; the
model itself cannot be trusted to obey the cap perfectly.

### `synthesis.py`

-   Combine proposals, repository observations, user answers, and
    disputes.
-   Produce decisions and a canonical specification model.
-   Preserve rejected alternatives and unresolved decisions.
-   Assign stable IDs to requirements and decisions.
-   Avoid silently converting uncertain claims into facts.

### `documents.py`

Generate the three Markdown documents from the canonical specification
and the saved decision records. Templates can be simple Python functions
at first. Use the same normalized source objects for repeated names and
contracts to reduce divergence.

### `verification.py`

Run deterministic checks such as: - Required files exist and are
non-empty. - Requirement IDs are unique. - Acceptance criteria reference
existing requirement IDs. - Required functional requirements have
acceptance criteria. - Major/critical disputes are resolved or
explicitly marked unresolved. - Key technology choices are consistent
across documents. - Repeated API paths, entity names, and module paths
agree where structured records are available. - No non-goal is
accidentally listed as an in-scope feature.

Save a machine-readable JSON report and a human-readable
`verification_report.md`. A language model may suggest repairs, but
Python must determine whether deterministic checks pass.

### `storage.py`

-   Write JSON with stable formatting.
-   Write Markdown using UTF-8.
-   Save stage outputs before moving on.
-   Maintain `meeting.json` with stage, status, timestamps, and artifact
    paths.
-   Preserve previous document revisions when applying patches.
-   Use atomic file replacement where practical to avoid partially
    written artifacts.

## 6. Gemini API Integration

### Configuration

`.env.example`:

``` dotenv
GEMINI_API_KEY=replace_with_your_key
GEMINI_MODEL=gemini-2.5-flash
```

The model value is configurable; use a currently available Gemini model
supported by the account and SDK. Do not assume a model name is
universally available forever.

`.gitignore` should include:

``` gitignore
.env
.venv/
__pycache__/
.pytest_cache/
output/
*.py[cod]
```

Install the official SDK and supporting libraries:

``` bash
python -m venv .venv
```

Windows PowerShell:

``` powershell
.venv\Scripts\Activate.ps1
pip install google-genai pydantic python-dotenv typer pytest
```

macOS/Linux:

``` bash
source .venv/bin/activate
pip install google-genai pydantic python-dotenv typer pytest
```

For reproducibility, pin compatible dependency versions in
`pyproject.toml` once the first working implementation has been tested.

### Client behavior

The client should: 1. Read the key from the environment. 2. Create a
Gemini SDK client. 3. Send a prompt with a structured output schema when
supported. 4. Parse and validate the response. 5. Retry transient errors
with bounded exponential backoff. 6. Fail with a clear message on
authentication, quota, or model configuration errors.

Do not log prompts or repository excerpts indiscriminately. Verbose
diagnostics should still redact secrets. The Gemini API is a cloud
service: only send repository excerpts the user has permitted the tool
to process.

## 7. Concurrency and Cost Controls

-   Run four independent proposal calls concurrently.
-   Set a small, configurable maximum number of concurrent calls.
-   Run review calls only after proposal results are saved.
-   Avoid having every agent review every claim repeatedly; one review
    pass is sufficient for MVP.
-   Cap repository context and proposal sizes.
-   Keep retries bounded.
-   Record model name, stage, elapsed time, and token usage if returned
    by the SDK.
-   Do not repeat a complete meeting for a targeted document edit.
-   Do not run experiments automatically in the first MVP; record
    suggested experiments as recommendations.

The expected call count depends on question curation and repair. Keep
the flow bounded rather than allowing open-ended debate.

## 8. Error Handling and Recovery

Handle these cases explicitly: - Missing API key. - Invalid or
unavailable model. - Quota/rate-limit response. - Network timeout. -
Malformed structured response. - One proposal agent failing. -
Repository not accessible. - No valid human questions. - Invalid
canonical specification. - Document write failure. - Verification
failure after the single repair pass. - User interruption.

Every failure should identify the stage and preserve already completed
artifacts. The CLI must not report a successful meeting if required
outputs are missing or verification failures remain hidden.

## 9. Testing Strategy

### Unit tests

-   Pydantic validation and invalid response handling.
-   Question maximum and default selection.
-   Severity filtering.
-   Secret-file exclusion and size limits.
-   Stable requirement/decision ID validation.
-   Document rendering.
-   Consistency checks.
-   Atomic writes and revision backups.

### Integration tests

Use a fake Gemini client so normal tests do not require network access
or incur API costs. Verify the full stage sequence and expected files.

### Live smoke test

Provide an opt-in test using a real Gemini API key to verify SDK
configuration and one small structured response. Do not run live API
calls in the default test suite.

### Adversarial tests

-   Repository files containing instructions that attempt to override
    the agent prompt.
-   `.env` and private key files in a repository.
-   Malformed or oversized manifests.
-   Model output containing invented requirement IDs.
-   Conflicting API contracts across documents.
-   Model output that attempts to exceed the question limit.

## 10. Implementation Order

### Milestone 1 --- CLI and Gemini

-   Create package and configuration.
-   Read problem statement and API key.
-   Implement one typed Gemini call.
-   Add unit tests for configuration and response parsing.

### Milestone 2 --- Repository snapshot and independent proposals

-   Implement safe local repository inspection.
-   Add four persona prompts.
-   Run proposals concurrently.
-   Save each proposal independently.

### Milestone 3 --- Review and human gate

-   Implement structured disputes.
-   Filter severities.
-   Deduplicate and cap questions.
-   Record human answers.

### Milestone 4 --- Synthesis and documents

-   Define canonical specification models.
-   Generate decisions and all three documents.
-   Save stage checkpoints and meeting metadata.

### Milestone 5 --- Verification and revision

-   Add deterministic cross-document checks.
-   Add one bounded repair pass.
-   Preserve document versions.
-   Complete fake-client end-to-end tests.

## 11. Definition of Done

The MVP is ready when: - A user can start it from the terminal with a
problem statement. - Gemini is the only model provider. - Four
independent proposal roles are run concurrently when calls succeed. -
Repository inspection is optional and read-only. - Material objections
and decisions are saved. - The human question count is deterministically
capped at five. - Three detailed Markdown documents are generated from a
canonical specification. - Deterministic consistency checks run and
produce a report. - One bounded repair pass is supported. - Failed calls
do not erase earlier artifacts. - Tests run without a live Gemini key by
using a fake client. - No frontend, database, message broker, or
autonomous coding agent is required.

## 12. Important Implementation Guardrails

-   Keep orchestration explicit and understandable; don't build a
    generic agent framework.
-   Use Pydantic models at LLM boundaries.
-   Treat model output as untrusted until validated.
-   Keep all Gemini SDK calls in one module.
-   Never execute project code during reconnaissance.
-   Never commit secrets or generated output by default.
-   Do not automatically push or commit to Git.
-   Avoid unbounded debate, retries, repair loops, or token budgets.
-   Make unresolved issues visible instead of manufacturing certainty.
