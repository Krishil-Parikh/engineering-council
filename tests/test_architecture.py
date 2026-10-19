"""The codebase is split into independent modules. This test enforces who may import whom, so the split cannot erode.

  harness      the coding agent engine (sessions, compaction, memory/instructions, tools, permissions, git)   imports: itself only
  council_a2a  Agent2Agent protocol over gRPC (official a2a-sdk)                                              imports: itself only
  memory       project memory and cross-project memory                                                         imports: itself only
  meetings     planning mode: the multi-agent meeting, documents, verification, TUI                            imports: council_a2a
  team         agent mode: autonomous developers, branches, merges, design meetings                            imports: harness, council_a2a, meetings, memory
  council      the application entry point that wires the modules together                                     imports: anything
  gateway      the web API the frontend talks to; translates between the frontend contract and the modules       imports: anything
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {
    "harness": {"harness"},
    "council_a2a": {"council_a2a"},
    "memory": {"memory"},
    "meetings": {"meetings", "council_a2a"},
    "team": {"team", "harness", "council_a2a", "meetings", "memory"},
    "council": {"council", "harness", "council_a2a", "memory", "meetings", "team"},
    "gateway": {"gateway", "council", "harness", "council_a2a", "memory", "meetings", "team"},
}
OURS = set(ALLOWED)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_modules_only_import_what_they_are_allowed_to():
    violations = []
    for module, allowed in ALLOWED.items():
        pkg = ROOT / module
        if not pkg.is_dir():
            continue
        for path in pkg.rglob("*.py"):
            bad = (imported_modules(path) & OURS) - allowed
            if bad:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(bad)} (allowed: {sorted(allowed)})")
    assert not violations, "\n".join(violations)


def test_every_top_level_package_is_a_known_module():
    """A new top-level package must be added to the table above on purpose."""
    skip = {"tests", "output", "node_modules", "Engineering_Council_System_Prompts"}
    packages = {p.name for p in ROOT.iterdir() if p.is_dir() and (p / "__init__.py").exists() and p.name not in skip and not p.name.startswith((".", "_"))}
    assert packages <= OURS, f"unregistered packages: {sorted(packages - OURS)}"
