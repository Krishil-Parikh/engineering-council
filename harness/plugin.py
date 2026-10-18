"""Hooks and plugins (opencode: the plugin host, packages/core/src/plugin).

A *hook* is a function the harness calls at a fixed point, so extra behaviour can be added without touching the engine:

  context       every model request's messages (may edit them)               {"sessionID", "agent", "messages", "synthetic"}
  tool.before   before a tool runs (may repair the input or rename the tool)  {"tool", "sessionID", "agent", "input", ...}
  tool.after    after a tool ran (may replace its result or its error)        {"tool", "status", "result"|"error", ...}
  input         a session has new input to talk about                         (session_id, count)
  event         everything the harness reports                                (kind, data)
  compaction.request  the request that asks the model for a summary (return a new one to replace it)
  compaction.summary  return {"summary": text} to write the summary yourself; the first plugin that does wins and no model is asked

A *plugin* is a Python file with a `plugin(api)` function. `api.hooks.add("tool.after", fn)` registers hooks, `api.add_tool(tool)` adds a tool,
`api.harness` is the running Harness. Plugins are read from `plugins/*.py` in every configuration directory and from the `plugins` list in
configuration (file paths). A plugin that fails to load, or a hook that raises, is reported (`host.errors`, the `plugin.error` event) and
skipped: a misbehaving plugin must never break a run."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from harness.config import service as cfg

log = logging.getLogger("harness.plugin")
HOOK_NAMES = ("context", "tool.before", "tool.after", "input", "event", "compaction.request", "compaction.summary")


class Hooks:
    def __init__(self, on_error: Optional[Callable[[str, str], None]] = None) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = {name: [] for name in HOOK_NAMES}
        self.on_error = on_error or (lambda name, message: None)

    def add(self, name: str, fn: Callable[..., Any]) -> None:
        if name not in self._hooks:
            raise ValueError(f"unknown hook {name!r}; the hooks are {', '.join(HOOK_NAMES)}")
        self._hooks[name].append(fn)

    def count(self, name: str) -> int:
        return len(self._hooks[name])

    def dispatcher(self, name: str) -> Callable[..., None]:
        """One function that calls every hook registered under `name`, in order. A hook that raises is reported and skipped."""

        def call(*args: Any) -> None:
            for fn in list(self._hooks[name]):
                try:
                    fn(*args)
                except Exception as exc:  # noqa: BLE001 - see the module docstring
                    log.warning("hook %s failed: %s", name, exc)
                    self.on_error(name, f"{type(exc).__name__}: {exc}")

        return call

    def pipeline(self, name: str) -> Callable[[Any], Any]:
        """A function that passes a value through the hooks in turn; a hook that returns something replaces the value, one that returns None leaves it."""

        def run(value: Any) -> Any:
            for fn in list(self._hooks[name]):
                try:
                    replaced = fn(value)
                except Exception as exc:  # noqa: BLE001
                    log.warning("hook %s failed: %s", name, exc)
                    self.on_error(name, f"{type(exc).__name__}: {exc}")
                    continue
                if replaced is not None:
                    value = replaced
            return value

        return run

    def first(self, name: str) -> Callable[..., Any]:
        """A function that returns the first non-None answer from the hooks, or None."""

        def run(*args: Any) -> Any:
            for fn in list(self._hooks[name]):
                try:
                    answer = fn(*args)
                except Exception as exc:  # noqa: BLE001
                    log.warning("hook %s failed: %s", name, exc)
                    self.on_error(name, f"{type(exc).__name__}: {exc}")
                    continue
                if answer is not None:
                    return answer
            return None

        return run


class PluginApi:
    def __init__(self, harness: Any, hooks: Hooks, path: Path) -> None:
        self.harness, self.hooks, self.path = harness, hooks, path

    def add_tool(self, tool: Any) -> None:
        self.harness.registry.add(tool)

    def override_tool(self, tool: Any) -> bool:
        return self.harness.registry.override(tool)

    def disable_tool(self, name: str) -> None:
        self.harness.registry.disable(name)


class PluginHost:
    def __init__(self, harness: Any, hooks: Hooks) -> None:
        self.harness, self.hooks = harness, hooks
        self.loaded: list[Path] = []
        self.errors: list[str] = []

    def discover(self, config: cfg.Config) -> list[Path]:
        """Plugin files named by configuration, then those in the `plugins` folder of each configuration directory (lower priority first)."""
        found: list[Path] = []
        for entry in config.entries():
            if isinstance(entry, cfg.Directory):
                found += sorted((entry.path / "plugins").glob("*.py")) if (entry.path / "plugins").is_dir() else []
            elif isinstance(entry, cfg.Document):
                base = entry.path.parent if entry.path else config.location.directory
                found += [(Path(base) / p).resolve() if not Path(p).is_absolute() else Path(p) for p in entry.info.get("plugins", []) if isinstance(p, str)]
        seen: list[Path] = []
        for p in found:
            if p not in seen:
                seen.append(p)
        return seen

    def load(self, path: Path) -> bool:
        name = "harness_plugin_" + "".join(c if c.isalnum() else "_" for c in str(path))
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot read {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            entry = getattr(module, "plugin", None)
            if not callable(entry):
                raise AttributeError("it defines no plugin(api) function")
            entry(PluginApi(self.harness, self.hooks, path))
        except Exception as exc:  # noqa: BLE001
            message = f"plugin {path.name} was not loaded: {type(exc).__name__}: {exc}"
            self.errors.append(message)
            log.warning(message)
            self.hooks.on_error("load", message)
            sys.modules.pop(name, None)
            return False
        self.loaded.append(path)
        return True

    def load_all(self, config: cfg.Config) -> None:
        for path in self.discover(config):
            self.load(path)
