# Skill — Mermaid diagrams and directory trees

Use this skill whenever you write or review an architecture diagram, a flow, a data model or a directory structure. Documents are only useful if the diagram renders and agrees with the text.

## Diagram types to use
- **System context** (PRD): `flowchart LR`. Actors and external systems around ONE box for the system.
- **Architecture** (Technical Approach): `flowchart TD`. One node per component from the component list, named exactly as in the list. Arrows point from the component that USES to the component it DEPENDS ON. Group with `subgraph Name ... end` only if there are more than 6 components.
- **Runtime flow**: `sequenceDiagram` with the same participant names as the components, or `flowchart TD` for pure step lists. Include one failure path.
- **Data model** (Design): `erDiagram` only when there are real stored entities.

## Syntax rules that keep diagrams rendering
- First line is the diagram type. No code fences inside the field; the document adds them.
- Node ids are alphanumeric, with no spaces, and never `end`, `graph`, `flowchart` or `subgraph`.
- Put every label in double quotes: `Api["Orders API<br/>app/api.py"]`. Never use parentheses, brackets, braces, `|` or quotes inside a label.
- Use `-->` for arrows and `-->|text|` for a labelled arrow (label text without special characters).
- Every `subgraph` has a matching `end`.
- Keep diagrams small: at most 15 nodes. Split a big system into several diagrams rather than one unreadable one.
- A diagram may only contain components, files, tools and actors that exist in the text. Do not invent a box to make the picture look complete.

## Directory tree rules
- A plain-text tree using `├──`, `└──`, `│`. One entry per line; folders end with `/`.
- Keep it as FLAT as the project allows: no packages or layers that only hold one file.
- Every component's `path` must be a file or folder that appears in the tree. Every important file in the tree must belong to a component, a test, a config or docs.
- Include tests, config and docs locations. Do not list generated or vendored folders.

## When reviewing
Ask: does the picture match the component list? Do the arrows match the stated dependency direction? Is anything in the tree that no component owns, or any component without a place in the tree? Say exactly what to rename, move, add or remove.
