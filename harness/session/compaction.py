"""Conversation compaction (opencode: packages/core/src/session/compaction.ts).

When the conversation approaches the model's window, the older part is replaced by a structured checkpoint written by the
model, and the newest part (about `keep` tokens) is kept verbatim as text beside it:

  first:  [E1 ... E8][E9 E10]                  ->  [S1 + "E9 E10"]
  again:  [S1 + "E9 E10"][E11 ... E18][E19]    ->  [S2 + "E19"]      (S2 covers S1, E9 E10 and E11-E18)

Later requests open with the checkpoint as one user message, then the new messages. History loading starts at the latest
completed compaction, so everything before it stays on disk but is never sent again.

Differences from opencode: no native (provider-side) compaction, which is an OpenAI-only mechanism, and no media-size passes."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from harness.ai import events as E
from harness.ai import types as T
from harness.ai.errors import AIError, error as ai_error, is_context_overflow_failure, is_retryable
from harness.ai.model import ModelLimit, ResolvedModel
from harness.schema import message as M
from harness.session import instruction_state as InstructionState
from harness.session import model_request as R
from harness.session import usage as SessionUsage
from harness.session.retry import RetryPolicy
from harness.session.store import SessionInfo, SessionStore
from harness.util import token as Token

SHRINK_STEPS = [0.7, 0.5, 0.35]  # after each "too long" rejection, aim at this share of the first rejected request's size
RESERVE_MIN = 16_000  # the least window kept free for the last reply and for the summary itself
UNKNOWN_WINDOW = 200_000  # assumed for the compaction request when the model's window is unknown
TOOL_OUTPUT_MAX_CHARS = 1_250
IMAGE_TOKEN_ESTIMATE = 1_500
PDF_TOKEN_ESTIMATE = 2_000
LEGACY_HEADING = "## Additional Context"

SUMMARY_TEMPLATE = """You MUST use this format for your response (you may omit sections that aren't applicable). Do not include the <template> tags in your response.
<template>
## Objective
- [one or two brief sentences describing what the user is trying to accomplish]

## Requirements
- [constraints, preferences, requirements, and scope boundaries stated by the user, or "(none)"]

## Decisions
- [decisions already made and why, or "(none)"]

## Work State
Break the objective into smaller goals and report which are completed, which are being worked on, and which are blocked.
### Completed
- [goals that have been completed; otherwise "(none)"]

### Active
- [goals currently being worked on; otherwise "(none)"]

### Blocked
- [anything blocking progress, and why; otherwise "(none)"]

## Next Move
1. [ordered list of next actions, or "(none)"]

## Relevant Files
List the files and directories, other than the current working directory, that another agent would need to open to continue this work. Include at most 15, most important first. Do not list every file that was read or changed. Include paths outside the current working directory when relevant. If none, write "(none)".
- `[file or directory path]`: [brief reason it matters]

## Important Context
- [facts the next agent cannot continue without and cannot easily find on its own; or "(none)"]
</template>"""

SUMMARY_RULES = """Rules:
- Keep each section concise. Use terse, single-line bullets, not prose paragraphs or nested lists.
- Prefer short references over detailed restatement. It is fine to leave out information the next agent can recover from the code or the files listed above.
- Preserve exact file paths, symbols, commands, error strings, URLs, and identifiers.
- Carry forward only user questions or requests that remain unanswered or require further action. Do not repeat ones that newer history has answered or resolved. Preserve exact wording when carrying one forward.
- Preserve consequential workflow state, including whether changes are uncommitted, committed, pushed, under review, or merged.
- Do not mention the summary process or that context was compacted."""

NUDGE = "The previous response did not fill in the required summary template. Do not call tools. Return the summary as text using the exact section headings from the template."


def build_prompt(update: bool, legacy: bool = False) -> str:
    shared = [
        "Summarize only what the user and the assistant said and did. Leave out instructions and setup the assistant was given rather than told by the user: repository conventions, instruction files such as AGENTS.md, and environment details like the session ID. The next agent receives current versions of all of these separately.",
        SUMMARY_TEMPLATE,
        SUMMARY_RULES,
        "Do not continue the task or call tools.",
        "Return only the structured summary in the requested format. Do not include a preamble, explanation, or other commentary.",
    ]
    if not update:
        return "\n\n".join(["You MUST summarize the conversation above into a structured summary that will be given to another agent to resume the work.", *shared])
    return "\n\n".join([
        "Update the existing checkpoint in the conversation above into one consolidated summary.",
        *(["The existing checkpoint was written with an earlier format that recorded far more detail than this one asks for. Rewrite it at the level of detail described below rather than carrying its detail forward. Keep its requirements, decisions, and open questions; they came from earlier conversation with the user."] if legacy else []),
        "Newer history always takes precedence over the existing checkpoint. Preserve previous information unless newer history clearly contradicts, supersedes, resolves, or makes it stale. If something is no longer relevant to continuing the work, you may remove it.",
        "Incorporate newer requirements, decisions, progress, and context. Reconcile Work State and Next Move: move completed work out of Active, remove resolved blockers and answered questions, and preserve unresolved or pending work.",
        "Return only the updated Markdown sections. Do not reproduce the `<conversation-checkpoint>`, `<summary>`, or `<recent-context>` wrapper tags from the previous checkpoint.",
        *shared,
    ])


# --------------------------------------------------------------------------- types


@dataclass
class AgentInfo:
    id: str
    system: Optional[str] = None
    steps: Optional[int] = None


@dataclass
class Loaded:
    """Everything one model request is built from (opencode: SessionContext.Loaded)."""

    session: SessionInfo
    agent: AgentInfo
    model: ResolvedModel
    initial: str
    messages: list[M.Info]
    tools: list[T.ToolEntry] = field(default_factory=list)


@dataclass
class Trigger:
    reason: str  # auto | overflow | manual
    context: Loaded


@dataclass
class Outcome:
    status: str  # skipped | completed | failed
    error: Optional[M.SessionError] = None


class Failure(Exception):
    """A reply that cannot be used; never retried."""

    def __init__(self, error: M.SessionError) -> None:
        super().__init__(error.message)
        self.error = error


NOTHING_TO_COMPACT = M.SessionError(type="compaction.unavailable", message="Nothing to compact yet")


@dataclass
class Settings:
    auto: bool = True
    keep: int = 15_000
    buffer: Optional[int] = None


@dataclass
class Result:
    text: str
    recent: str
    provider_state: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass
class Streamed:
    text: str = ""
    provider_state: Optional[dict[str, Any]] = None


# --------------------------------------------------------------------------- estimation


def _estimate_tool(tool: T.ToolEntry) -> int:
    return Token.estimate(tool.name + tool.description + T.json_dumps(tool.input_schema))


def _estimate_media(mime: str) -> int:
    t = mime.lower()
    if t.startswith("image/"):
        return IMAGE_TOKEN_ESTIMATE
    if t == "application/pdf":
        return PDF_TOKEN_ESTIMATE
    return 0


def _estimate_part(part: T.ContentPart) -> int:
    if isinstance(part, T.CompactionPart):
        return Token.estimate(part.text or "")
    if isinstance(part, (T.TextPart, T.ReasoningPart)):
        return Token.estimate(part.text)
    if isinstance(part, T.MediaPart):
        return _estimate_media(part.media.media_type)
    if isinstance(part, T.ToolCallPart):
        return Token.estimate(part.name + (T.json_dumps(part.input) or ""))
    res = part.result  # ToolResultPart
    if res.type == "content":
        return sum(Token.estimate(c["text"]) if c.get("type") == "text" else _estimate_media(c.get("mime", "")) for c in res.value)
    v = res.value
    return Token.estimate(v if isinstance(v, str) else (T.json_dumps(v) or ""))


def estimate_message(message: T.Message) -> int:
    return sum(_estimate_part(p) for p in message.content)


def estimate_request(system: list[T.SystemPart], tools: list[T.ToolEntry], messages: list[T.Message]) -> int:
    return sum(Token.estimate(p.text) for p in system) + sum(_estimate_tool(t) for t in tools) + sum(estimate_message(m) for m in messages)


def _transcript(context: Loaded, messages: list[M.Info]) -> R.Transcript:
    return R.base_transcript(
        agent_system=context.agent.system, model=context.model, tool_names=[t.name for t in context.tools], initial=context.initial, messages=messages
    )


def _has_measured_prompt(message: M.Info, provider_id: str) -> bool:
    return (
        isinstance(message, M.Assistant)
        and message.model.provider_id == provider_id
        and message.error is None
        and message.tokens is not None
        and message.tokens.input + message.tokens.cache_read + message.tokens.cache_write > 0
    )


def estimate_prompt(context: Loaded) -> R.InputTokens:
    """measured = what the provider reported at the latest response; estimated = the text since."""
    anchor_index = next((i for i in range(len(context.messages) - 1, -1, -1) if _has_measured_prompt(context.messages[i], context.model.ref.provider_id)), -1)
    anchor = context.messages[anchor_index] if anchor_index >= 0 else None
    base = _transcript(context, context.messages[max(0, anchor_index):])
    # The anchor's usage covers its own output, but not its local tool results, which the provider never saw.
    unmeasured = [m for m in base.messages if m.role != "assistant" or m.id != (anchor.id if anchor else None)]
    if not isinstance(anchor, M.Assistant) or not anchor.tokens:
        return R.InputTokens(0, estimate_request(base.system, context.tools, unmeasured))
    t = anchor.tokens
    return R.InputTokens(t.input + t.cache_read + t.cache_write + t.output + t.reasoning, sum(estimate_message(m) for m in unmeasured))


def estimate_context(context: Loaded) -> float:
    p = estimate_prompt(context)
    return p.measured + p.estimated


def calculate_ceiling(limit: ModelLimit, buffer: Optional[int]) -> float:
    """The largest request the model takes while leaving room for its reply: 10% of the window, or RESERVE_MIN when that is more."""
    window = limit.input or limit.context
    if window <= 0:
        return math.inf
    if buffer is not None:
        return window - buffer
    return window - max(math.floor(window * 0.1), RESERVE_MIN if window >= 2 * RESERVE_MIN else 0)


# --------------------------------------------------------------------------- text rendering of history


def truncate_tool_output(value: str) -> str:
    if len(value) <= TOOL_OUTPUT_MAX_CHARS:
        return value
    return value[:TOOL_OUTPUT_MAX_CHARS] + "\n[truncated]"  # str indexes code points, so a surrogate pair is never split


def _serialize_tool_content(content: list[Any]) -> str:
    out = []
    for item in content:
        if item["type"] == "text":
            out.append(item["text"])
        else:
            out.append(f"[Attached {item['mime']}{'' if item.get('name') is None else ': ' + item['name']}]")
    return "\n".join(out)


def message_to_text(message: M.Info) -> str:
    """One message as the recent, verbatim part of a summary shows it. Empty for messages that part leaves out."""
    if isinstance(message, (M.CompactionRunning, M.CompactionCompleted, M.CompactionFailed, M.System)):
        return ""
    if isinstance(message, M.User):
        skills = [f"[Skill activated: {s.name}]\n{s.text}" for s in (message.skills or []) if s.text is not None]
        files = [f"[Attached {f.mime}: {f.name or (f.source.get('uri') if f.source.get('type') == 'uri' else 'inline attachment')}]" for f in (message.files or [])]
        return "\n".join([*skills, f"[User]: {message.text}", *files])
    if isinstance(message, M.LocationSwitched):
        return f"[User]: The working directory has been changed to {message.location.directory}."
    if isinstance(message, M.Assistant):
        lines: list[str] = []
        for part in message.content:
            if isinstance(part, M.AssistantText):
                lines.append(f"[Assistant]: {part.text}")
            elif isinstance(part, M.AssistantReasoning):
                if part.text:
                    lines.append(f"[Assistant reasoning]: {part.text}")
            else:
                st = part.state
                inp = st.input if isinstance(st.input, str) else json.dumps(st.input, separators=(",", ":"))
                call = f"[Assistant tool call]: {part.name}({inp})"
                if st.status == "completed":
                    lines += [call, f"[Tool result]: {truncate_tool_output(_serialize_tool_content([c.model_dump(exclude_none=True) for c in st.content]))}"]
                elif st.status == "error":
                    lines += [call, f"[Tool error]: {st.error.message}"]
                else:
                    lines.append(call)
        return "\n".join(lines)
    if isinstance(message, M.Synthetic):
        return f"[Synthetic context]: {message.text}"
    if isinstance(message, M.Skill):
        return f"[Skill activated: {message.name}]\n{message.text}"
    if isinstance(message, M.ShellMessage):
        if (message.metadata or {}).get("background") is True:
            return ""
        return f"[Shell]: {message.command}\n{truncate_tool_output((message.output or {}).get('output', ''))}"
    return ""


def _flatten_message(message: T.Message) -> str:
    """One request message as a flattened transcript line. Empty for what the transcript leaves out."""
    if message.role == "system":
        return ""
    lines: list[str] = []
    for part in message.content:
        if isinstance(part, T.TextPart):
            if part.text:
                lines.append(f"[{'User' if message.role == 'user' else 'Assistant'}]: {part.text}")
        elif isinstance(part, T.MediaPart):
            lines.append(f"[{part.media.media_type} omitted]")
        elif isinstance(part, T.ToolCallPart):
            lines.append(f"[Assistant tool call]: {part.name}({T.json_dumps(part.input)})")
        elif isinstance(part, T.ToolResultPart):
            r = part.result
            if r.type == "content":
                output = _serialize_tool_content(r.value)
            else:
                output = r.value if isinstance(r.value, str) else T.json_dumps(r.value)
            label = "Tool error" if r.type == "error" else "Tool result"
            lines.append(f"[{label}]: {truncate_tool_output(output)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- splitting


def oldest_to_drop(items: list[Any], size: Callable[[Any], int], budget: float) -> int:
    total, start = 0, len(items)
    while start > 0:
        nxt = total + size(items[start - 1])
        if nxt > budget:
            break
        total = nxt
        start -= 1
    return start


def previous_compaction(messages: list[M.Info]) -> Optional[M.CompactionCompleted]:
    """History loads from the latest completed compaction, so a previous one is always the first message."""
    first = messages[0] if messages else None
    return first if isinstance(first, M.CompactionCompleted) else None


def _recent_start(entries: list[dict[str, Any]], keep: int, previous: Optional[M.CompactionCompleted]) -> int:
    # Drop the oldest entries until the rest fit the allowance, but always keep the newest one.
    dropped = min(oldest_to_drop(entries, lambda e: Token.estimate(e["text"]), keep), len(entries) - 1)
    # Start at a user message so an assistant's tool calls and results stay together.
    user_boundary = next((i for i in range(len(entries) - 1, -1, -1) if i <= dropped and isinstance(entries[i]["message"], M.User)), -1)
    if user_boundary > 0:
        return user_boundary
    # Everything fits. Keep only the latest exchange so there is an older part left to summarize.
    latest_user = next((i for i in range(len(entries) - 1, -1, -1) if isinstance(entries[i]["message"], M.User)), -1)
    if latest_user > 0:
        return latest_user
    # One exchange, nothing older. Summarize it all and keep nothing, unless a previous summary already kept recent text.
    return 0 if previous is not None and previous.recent else len(entries)


@dataclass
class Split:
    older: list[M.Info]
    recent: str


def split_conversation(messages: list[M.Info], keep: int) -> Optional[Split]:
    """`older` gets summarized; `recent`, the newest messages within `keep` tokens, is kept verbatim as text beside the summary."""
    entries = []
    for index, message in enumerate(messages):
        text = message_to_text(message)
        if text:
            entries.append({"message": message, "text": text, "index": index})
    if not entries:
        return None
    recent = entries[_recent_start(entries, keep, previous_compaction(messages)):]
    return Split(messages[: recent[0]["index"] if recent else len(messages)], "\n\n".join(e["text"] for e in recent))


def flatten_and_drop_oldest(request: T.LLMRequest, context: Loaded, target: float) -> Optional[T.LLMRequest]:
    """History that has to change is sent as text: [previous compaction][transcript]. The transcript leaves out reasoning, media and
    instruction updates, and cuts long tool outputs. Only if it still does not fit are whole exchanges dropped, oldest first."""
    previous = previous_compaction(context.messages)
    end = 0
    for i in range(len(request.messages) - 1, -1, -1):
        m = request.messages[i]
        if (previous is not None and m.id == previous.id) or any(isinstance(p, T.CompactionPart) for p in m.content):
            end = i + 1
            break
    summary = previous
    # A previous summary always stays in front, while its verbatim recent part becomes the oldest transcript entry.
    if summary is not None:
        from harness.session.to_llm_message import to_llm_messages

        lead = to_llm_messages([summary.model_copy(update={"recent": ""})], context.model.ref, context.model.metadata_key)
    else:
        lead = request.messages[:end]
    exchanges: list[str] = [summary.recent] if summary is not None and summary.recent else []
    for message in request.messages[end:]:
        text = _flatten_message(message)
        if not text:
            continue
        if message.role == "user" or not exchanges:
            exchanges.append(text)
        else:
            exchanges[-1] += f"\n{text}"

    def note(omitted: int) -> str:
        return f"[{omitted} older {'exchange' if omitted == 1 else 'exchanges'} omitted]\n\n" if omitted else ""

    room = target - estimate_request(request.system, request.tools, lead) - Token.estimate(note(len(exchanges)))
    kept = exchanges[oldest_to_drop(exchanges, lambda text: Token.estimate(text) + 1, room):]
    if not kept:
        return None
    return request.update(messages=[*lead, T.Message.user(note(len(exchanges) - len(kept)) + "\n\n".join(kept))])


def _fit_output(request: T.LLMRequest, limit: ModelLimit) -> T.LLMRequest:
    """Lower the output limit to the room the request being sent leaves in the window, by our own estimate."""
    current = request.generation.max_tokens if request.generation else None
    if current is None:
        return request
    mx = min(current, R.output_limit(limit, "compaction", R.InputTokens(estimate_request(request.system, request.tools, request.messages), 0)))
    if mx == current:
        return request
    return request.update(generation=T.Generation(max_tokens=mx, temperature=request.generation.temperature, top_p=request.generation.top_p))


# --------------------------------------------------------------------------- the service

Observer = Callable[[str, dict[str, Any]], None]


class Compaction:
    def __init__(
        self, store: SessionStore, llm: E.LLMClient, *, settings: Optional[Settings] = None, observer: Optional[Observer] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, request_hook: Optional[Callable[[T.LLMRequest], T.LLMRequest]] = None,
        summary_hook: Optional[Callable[[Loaded, T.LLMRequest], Optional[dict[str, Any]]]] = None,
    ) -> None:
        self.store = store
        self.llm = llm
        self.settings = settings or Settings()
        self.observer = observer
        self.sleep = sleep
        self.request_hook = request_hook
        self.summary_hook = summary_hook  # may return {"summary": str} so no model call happens
        self._spent: dict[str, SessionUsage.Recorded] = {}

    def _emit(self, kind: str, **data: Any) -> None:
        if self.observer:
            self.observer(kind, data)

    # ---- due?
    def _due(self, context: Loaded, ceiling: float) -> bool:
        last = context.messages[-1] if context.messages else None
        if isinstance(last, M.CompactionCompleted):
            return False  # a compaction just completed; let the runner rebuild the request from it first
        return estimate_context(context) >= ceiling

    async def compact(self, trigger: Trigger) -> Outcome:
        context, settings = trigger.context, self.settings
        # Only the user compacts when automatic compaction is off, overflow included.
        if trigger.reason != "manual" and not settings.auto:
            return Outcome("skipped")
        if trigger.reason == "auto" and not self._due(context, calculate_ceiling(context.model.limit, settings.buffer)):
            return Outcome("skipped")
        ceiling = calculate_ceiling(context.model.limit, settings.buffer)
        # An unknown window never triggers auto compaction, but the compaction request still needs a size to aim for.
        cap = ceiling if math.isfinite(ceiling) else calculate_ceiling(ModelLimit(UNKNOWN_WINDOW, context.model.limit.input, context.model.limit.output), settings.buffer)
        # The provider just rejected this context, so the estimate ran low; the first attempt already aims below it.
        budget = min(cap, math.floor(estimate_context(context) * SHRINK_STEPS[0])) if trigger.reason == "overflow" else cap
        try:
            result = await self._summarize(trigger, budget, settings.keep)
        except Failure as failure:
            return self._publish_failed(trigger, failure.error)
        except AIError as err:
            return self._publish_failed(trigger, M.SessionError(type="provider.error", message=str(err)))
        except asyncio.CancelledError:
            self._publish_failed(trigger, M.SessionError(type="compaction.interrupted", message="Compaction was interrupted"))
            raise
        else:
            return self._publish_ended(trigger, result)
        finally:
            self._spent.pop(trigger.context.session.id, None)

    # ---- summarize
    async def _summarize(self, trigger: Trigger, budget: float, keep: int) -> Result:
        context = trigger.context
        split = split_conversation(context.messages, keep)
        if split is None:
            raise Failure(NOTHING_TO_COMPACT)
        previous = previous_compaction(context.messages)
        prompt = build_prompt(previous is not None, bool(previous and LEGACY_HEADING in previous.summary))
        headings = [ln for ln in SUMMARY_TEMPLATE.split("\n") if ln.startswith("##")]

        def filled(text: str) -> bool:
            return any(ln.strip() in headings for ln in text.split("\n"))

        request = self._prepare(context, split.older, budget)

        async def send(req: T.LLMRequest) -> Result:
            prompted = _fit_output(req.update(messages=[*req.messages, T.Message.user(prompt)]), context.model.limit)
            reply = await self._stream(context, prompted)
            if filled(reply.text):
                return Result(reply.text, split.recent, reply.provider_state)
            nudged = _fit_output(prompted.update(messages=[*prompted.messages, T.Message.user(NUDGE)]), context.model.limit)
            retry = await self._stream(context, nudged)
            if filled(retry.text):
                return Result(retry.text, split.recent, retry.provider_state)
            raise Failure(M.SessionError(type="compaction.failed", message="Compaction summary did not match the required template" if retry.text.strip() else "Compaction produced no summary"))

        overhead = Token.estimate(prompt) + Token.estimate(NUDGE)
        self._publish_started(trigger, split.recent)
        if self.summary_hook is not None:
            supplied = self.summary_hook(context, request)
            if supplied is not None:  # a hook supplied the summary itself, so no model call happens
                return Result(supplied["summary"], split.recent, supplied.get("provider_state"), supplied.get("metadata"))
        return await self._deliver(trigger, request, budget - overhead, send)

    def _prepare(self, context: Loaded, messages: list[M.Info], budget: float) -> T.LLMRequest:
        base = _transcript(context, messages)
        request = T.LLMRequest(
            system=base.system, tools=list(context.tools), messages=base.messages,
            generation=T.Generation(max_tokens=R.output_limit(context.model.limit, "compaction", R.InputTokens(budget, 0))),
        )
        return self.request_hook(request) if self.request_hook else request

    async def _deliver(self, trigger: Trigger, prepared: T.LLMRequest, target: float, send: Callable[[T.LLMRequest], Awaitable[Result]]) -> Result:
        """Sends the request as-is if it is estimated to fit `target`, and as text otherwise. A "too long" rejection means the estimate
        ran low, so the next attempts aim at 70%, 50%, then 35% of the first rejected request's estimate; a rejection after those gives
        up. A "payload too large" rejection is about bytes: it resends as text without counting. Other provider errors go through
        the retry policy. A Failure from `send` is never retried."""
        context = trigger.context
        policy = RetryPolicy()
        rejections = 0
        rejected: Optional[float] = None
        as_text = False
        while True:
            fits = not as_text and estimate_request(prepared.system, prepared.tools, prepared.messages) <= target
            if fits:
                request: Optional[T.LLMRequest] = prepared
            else:
                request = flatten_and_drop_oldest(prepared, context, target)
                if request is None:
                    if rejections > 0:
                        request = None
                    elif as_text:
                        request = flatten_and_drop_oldest(prepared, context, math.inf)
                    else:
                        request = prepared
            if request is None:
                raise Failure(M.SessionError(type="compaction.failed", message="The compaction request cannot be reduced further without losing the latest exchange or checkpoint"))
            try:
                return await send(request)
            except Failure:
                raise
            except AIError as cause:
                too_large = cause.reason.tag == "InvalidRequest" and cause.reason.classification == "payload-too-large"
                if too_large and request is prepared:
                    as_text = True
                    continue
                if too_large or is_context_overflow_failure(cause):
                    if rejections >= len(SHRINK_STEPS):
                        raise
                    if rejected is None:
                        rejected = estimate_request(request.system, request.tools, request.messages)
                    target = math.floor(rejected * SHRINK_STEPS[rejections])
                    rejections += 1
                    continue
                decision = policy.decide(cause, retry=is_retryable(cause))
                if not decision.retry:
                    raise
                await self.sleep(decision.delay_ms / 1000)

    async def _stream(self, context: Loaded, request: T.LLMRequest) -> Streamed:
        out = Streamed()
        key = context.model.metadata_key
        async for event in self.llm.stream(request):
            if isinstance(event, E.ProviderError):
                if event.classification is None:
                    raise Failure(M.SessionError(type="provider.error", message=event.message))
                raise ai_error("InvalidRequest", event.message, classification=event.classification)
            if isinstance(event, E.TextDelta):
                self._emit("compaction.delta", session=context.session.id, text=event.text)
                out.text += event.text
            elif isinstance(event, E.StepFinish):
                self._spend(context, SessionUsage.record(event.usage, context.model.cost))
                out.provider_state = (event.provider_metadata or {}).get(key, out.provider_state)
            elif isinstance(event, E.Finish):
                reason = event.normalized
                if reason == "unknown":
                    raise ai_error("InvalidProviderOutput", "The provider response ended with an unknown finish reason.", classification="incomplete-stream")
                if reason == "error":
                    raise ai_error("UnknownProvider", "Compaction generation failed")
                if reason == "length":
                    raise Failure(M.SessionError(type="compaction.failed", message="Compaction summary reached the output token limit"))
                if reason == "content-filter":
                    raise Failure(M.SessionError(type="content-filter", message="Compaction summary was blocked by the provider"))
        return out

    # ---- accounting and messages
    def _spend(self, context: Loaded, usage: SessionUsage.Recorded) -> None:
        total = self._spent.get(context.session.id)
        self._spent[context.session.id] = SessionUsage.add(total, usage) if total else usage
        self.store.add_usage(context.session.id, usage.cost, usage.tokens)
        self._emit("usage", session=context.session.id, source="compaction", cost=usage.cost)

    def _latest_compaction(self, session_id: str) -> Optional[tuple[int, M.Info]]:
        row = self.store.db.get("select * from session_message where session_id = ? and type = 'compaction' order by seq desc limit 1", (session_id,))
        return (row["seq"], SessionStore.decode_row(row)) if row else None

    def _publish_started(self, trigger: Trigger, recent: str) -> None:
        reason = "manual" if trigger.reason == "manual" else "auto"
        self.store.add(trigger.context.session.id, M.CompactionRunning(reason=reason, summary="", recent=recent))
        self._emit("compaction.started", session=trigger.context.session.id, reason=reason)

    def _publish_ended(self, trigger: Trigger, result: Result) -> Outcome:
        sid = trigger.context.session.id
        reason = "manual" if trigger.reason == "manual" else "auto"
        usage = self._spent.get(sid)
        found = self._latest_compaction(sid)
        completed = M.CompactionCompleted(
            id=found[1].id if found and isinstance(found[1], M.CompactionRunning) else M.new_message_id(),
            reason=reason, model=trigger.context.model.ref, provider_state=result.provider_state, summary=result.text, recent=result.recent,
            cost=usage.cost if usage else None, tokens=usage.tokens if usage else None, metadata=result.metadata,
        )
        with self.store.db.transaction():
            if found and isinstance(found[1], M.CompactionRunning):
                self.store.save(sid, completed)
                seq = found[0]
            else:
                _, seq = self.store.add(sid, completed)
            # The baseline folds in every instruction update so far; the system messages before this checkpoint are retired.
            InstructionState.advance_epoch(self.store.db, sid, seq)
        self._emit("compaction.ended", session=sid, reason=reason)
        return Outcome("completed")

    def _publish_failed(self, trigger: Trigger, err: M.SessionError) -> Outcome:
        sid = trigger.context.session.id
        reason = "manual" if trigger.reason == "manual" else "auto"
        usage = self._spent.get(sid)
        found = self._latest_compaction(sid)
        failed = M.CompactionFailed(
            id=found[1].id if found and isinstance(found[1], M.CompactionRunning) else M.new_message_id(), reason=reason, error=err,
            cost=usage.cost if usage else None, tokens=usage.tokens if usage else None,
        )
        if found and isinstance(found[1], M.CompactionRunning):
            self.store.save(sid, failed)
        else:
            self.store.add(sid, failed)
        self._emit("compaction.failed", session=sid, error=err.message)
        return Outcome("failed", err)
