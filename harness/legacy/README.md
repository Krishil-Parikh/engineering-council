# harness.legacy

A terminal coding agent harness modelled on [opencode](https://github.com/anomalyco/opencode), in Python, on Gemini function calling.
It is deliberately a separate package: nothing in here imports `meetings`. The council uses it (see `meetings/build.py`);
you can also run it on its own.

```
python -m harness.legacy -d path/to/project            interactive session
python -m harness.legacy -d path/to/project "fix the failing test"
python -m harness.legacy --continue                    resume the last session
```

Interactive commands: `/undo` (restore files and conversation to before your last message), `/compact`, `/agent plan`, `/init`, `/todos`, `/sessions`, `/exit`.

## What it has (and where opencode's equivalent lives)

| Capability | Here | opencode |
|---|---|---|
| Tools: `read` `glob` `grep` `edit` `write` `patch` `shell` `webfetch` `skill` `question` `todo` `subagent` | `tools/` | `core/src/tool/plugin/*` |
| Exact-match edit with tolerant fallback (curly quotes, trailing space, CRLF), read-before-edit and stale-file guard | `tools/files.py` | `tool/plugin/edit.ts`, file-time |
| `*** Begin Patch` multi-file patches | `tools/patch.py` | `tool/plugin/patch.ts` |
| Shell with timeout, background jobs, completion notifications, tail truncation, no terminal prompts | `tools/shell.py`, `jobs.py` | `tool/plugin/shell.ts`, `job.ts` |
| Git and GitHub: through the shell (`git`, `gh`), with commit/PR protocol in the system prompt and risky commands gated | `prompts/system.txt`, `agents.py` | bash tool description + permissions |
| Permissions: ordered rules, last match wins, `allow` / `deny` / `ask`, remembered approvals | `permission.py`, `agents.py` | `permission.ts` |
| Agents: `build`, `plan` (read-only), `explore` and `general` subagents; custom developer agents | `agents.py` | `plugin/agent.ts` |
| Step loop, retry with backoff and `retry-after`, step limit, empty-reply and output-limit recovery, repeated-call detection | `runner.py` | `session/runner/*` |
| Subagents in child sessions, foreground or background, resumable by `sessionID` | `runner.py` (`_spawn`), `tools/misc.py` | `tool/plugin/subagent.ts` |
| **Memory 1: instructions**: `AGENTS.md`/`CLAUDE.md` (global, project chain, nearby files on read), re-announced when they change | `memory.py` | `instruction-discovery.ts`, `read.ts` |
| **Memory 2: skills**: `SKILL.md` folders in `.council/skills`, `.claude/skills`, `.agents/skills` | `memory.py`, `tools/misc.py` | `skill.ts` |
| **Memory 3: conversation**: prune stale tool output, then summarise the old part into a structured checkpoint (Objective / Requirements / Decisions / Work State / Next Move / Relevant Files); retry on context overflow | `compaction.py` | `session/compaction.ts` |
| Sessions saved as an append-only log, resumable | `session.py` | session store |
| Undo through a private shadow git repository (never touches the project's own history) | `snapshot.py` | `snapshot.ts` |
| Large tool output saved to a file, tail returned | `tools/base.py` | `tool-output.ts` |

Not ported: LSP diagnostics, formatters, MCP servers, web search providers, images/PDF reading, the desktop/web UI.

## Safety defaults

- Nothing outside the project directory (and the harness scratch folder) can be read or changed without an `external_directory` approval.
- `read` of `.env` files, `sudo`, `rm -rf`, `git push`, `git reset --hard`, `git clean`, `git config`, `gh pr merge`, publishing commands: **ask**. With nobody to ask (unattended runs) an `ask` becomes a refusal that tells the model what was declined.
- `gh repo delete`: always denied.
- Commits use your git identity; if the machine has none, a placeholder identity is supplied through environment variables. The agent never rewrites git config.
- Identical tool calls repeated three times in a row are refused and, after repeated attempts, the run is stopped.

## Configuration

`council.json` (project root or `.council/config.json`) and `~/.council-harness/config.json`:

```json
{
  "context_window": 200000,
  "permission": { "shell": { "git push *": "allow", "npm publish *": "deny" }, "edit": "allow" },
  "agents": { "build": { "steps": 150 } }
}
```

Data (sessions, snapshots, saved approvals, truncated tool output) lives under `~/.council-harness/projects/<project>-<hash>/` (`HARNESS_HOME` overrides).
Model: `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.1-flash-lite`).

## Layout

```
harness.legacy/
├── cli.py            terminal front end
├── runner.py         the agent loop, retries, subagents, undo
├── agents.py         build / plan / explore / general + developer agents, default permission rules
├── permission.py     rules, wildcards, approvals
├── memory.py         AGENTS.md discovery + skills
├── compaction.py     conversation memory
├── session.py        message log and metadata
├── snapshot.py       shadow-git file snapshots
├── jobs.py           background shell commands and subagents
├── llm_gemini.py     Gemini tool-calling adapter (thought signatures preserved)
├── config.py  workspace.py  types.py
├── prompts/          system, plan, explore, init, max-steps prompts
└── tools/            files.py  patch.py  shell.py  misc.py  base.py
```

## The council builds with it

`python -m council build <meeting dir>`: the scrum master takes the specification's implementation sequence in order and hands
each step to the developer whose skill fits it. Each developer works as a harness `build` agent wearing their skill lens, in `<meeting dir>/project`
(which starts with `docs/` copies of the three documents and a generated `AGENTS.md` carrying the directory layout, stack and commands),
commits per step, and the specification's verification commands run at the end with bounded repair rounds. `--yes` approves ordinary
permission prompts but still refuses pushes and other risky commands. The result is `build_report.md`.
