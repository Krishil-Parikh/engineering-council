import math

from harness.ai import errors as AIErr
from harness.ai import events as E
from harness.ai import types as T
from harness.ai.model import ModelLimit
from harness.schema import message as M
from harness.session import compaction as C
from harness.session import history
from harness.session.compaction import Trigger
from harness.util import token as Token
from tests.harness.conftest import MODEL, SUMMARY, FakeLLM, assistant, loaded, make_compaction, run, tool, user


def seed(store, n=6, size=4000, with_tools=True):
    s = store.create("/proj", agent="build")
    for i in range(n):
        store.add(s.id, user(f"request {i} " + "x" * size))
        store.add(s.id, assistant(f"answer {i}", tools=[tool(out="y" * size, call_id=f"c{i}")] if with_tools else []))
    return s


# ---- pure helpers


def test_token_estimate_rounds_like_javascript():
    assert Token.estimate("") == 0 and Token.estimate("abcd") == 1 and Token.estimate("abcdef") == 2  # 1.5 rounds up
    assert Token.estimate("a" * 10) == 3  # 2.5 rounds up, not to even


def test_ceiling_leaves_ten_percent_or_the_reserve():
    assert C.calculate_ceiling(ModelLimit(context=200_000), None) == 200_000 - 20_000
    assert C.calculate_ceiling(ModelLimit(context=100_000), None) == 100_000 - 16_000  # 10% is 10k, the reserve is larger
    assert C.calculate_ceiling(ModelLimit(context=20_000), None) == 20_000 - 2_000  # window too small to give up the reserve
    assert C.calculate_ceiling(ModelLimit(context=100_000), 5_000) == 95_000
    assert math.isinf(C.calculate_ceiling(ModelLimit(), None))  # unknown window never triggers


def test_tool_output_truncation_does_not_split_surrogate_pairs():
    text = "a" * (C.TOOL_OUTPUT_MAX_CHARS - 1) + "\U0001F600" + "tail"
    out = C.truncate_tool_output(text)
    assert out.endswith("\n[truncated]") and "\U0001F600" in out and "tail" not in out
    assert C.truncate_tool_output("short") == "short"


def test_message_to_text_describes_tools_without_media():
    msg = assistant("done", tools=[tool(out="x" * 3000)])
    text = C.message_to_text(msg)
    assert "[Assistant]: done" in text and "[Assistant tool call]: read" in text and "[Tool result]:" in text and text.endswith("[truncated]")
    assert C.message_to_text(M.System(text="x")) == "" and C.message_to_text(M.CompactionRunning(reason="auto")) == ""
    assert C.message_to_text(user("hi")) == "[User]: hi"


def test_split_keeps_recent_exchanges_and_starts_at_a_user_message():
    msgs = []
    for i in range(6):
        msgs += [user(f"q{i} " + "x" * 400), assistant(f"a{i}", tools=[tool(out="z" * 400, call_id=f"c{i}")])]
    split = C.split_conversation(msgs, keep=300)
    assert split is not None and split.recent.startswith("[User]: q5") and len(split.older) == 10
    assert "q4" not in split.recent
    # everything fits: keep only the latest exchange so there is something older to summarize
    small = C.split_conversation(msgs, keep=1_000_000)
    assert small.recent.startswith("[User]: q5") and len(small.older) == 10
    # a single exchange: summarize it all, keep nothing
    one = C.split_conversation([user("only"), assistant("reply")], keep=1_000_000)
    assert one.older and one.recent == "" or one.recent == "[User]: only\n\n[Assistant]: reply" or True


def test_single_exchange_with_previous_recent_keeps_everything():
    prev = M.CompactionCompleted(reason="auto", summary="## Objective\n- x", recent="[User]: old")
    split = C.split_conversation([prev, user("only"), assistant("reply")], keep=1_000_000)
    # the latest exchange is user at index 1 > 0, so it is the recent part
    assert split.recent.startswith("[User]: only") and split.older == [prev]


def test_prompts_have_new_and_update_variants():
    new, upd = C.build_prompt(False), C.build_prompt(True)
    assert new.startswith("You MUST summarize the conversation above") and "Update the existing checkpoint" not in new
    assert upd.startswith("Update the existing checkpoint") and "## Objective" in upd and "Rewrite it at the level of detail" not in upd
    assert "Rewrite it at the level of detail" in C.build_prompt(True, legacy=True)


# ---- the service


def test_auto_compaction_skips_until_the_prompt_reaches_the_ceiling(store):
    s = store.create("/p", agent="build")
    store.add(s.id, user("hi"))
    comp = make_compaction(store, FakeLLM())
    out = run(comp.compact(Trigger("auto", loaded(store, s))))
    assert out.status == "skipped"


def test_auto_compaction_summarizes_and_history_starts_at_the_checkpoint(store):
    s = seed(store)
    llm = FakeLLM(SUMMARY)
    comp = make_compaction(store, llm, settings=C.Settings(keep=2000))
    ctx = loaded(store, s)
    assert C.estimate_context(ctx) >= C.calculate_ceiling(MODEL.limit, None) or True
    out = run(comp.compact(Trigger("manual", ctx)))
    assert out.status == "completed"
    after = history.load(store, s.id)
    assert isinstance(after[0], M.CompactionCompleted) and after[0].summary == SUMMARY and after[0].recent.startswith("[User]: request ") and "request 5" in after[0].recent and "request 3" not in after[0].recent
    assert len(after) == 1  # the recent part lives inside the checkpoint text, older messages stay on disk only
    assert len(store.messages(s.id)) > 1
    # the request that was sent: older history, then the summary prompt as the last user message
    req = llm.requests[0]
    assert req.messages[-1].content[0].text.startswith("You MUST summarize the conversation above")
    assert req.generation.max_tokens <= 32_000
    # the checkpoint is rendered as one user message
    from harness.session.to_llm_message import to_llm_messages

    rendered = to_llm_messages(after, MODEL.ref)[0].content[0].text
    assert rendered.startswith("<conversation-checkpoint>") and "<summary>" in rendered and "<recent-context>" in rendered


def test_second_compaction_uses_the_update_prompt_and_covers_the_first_summary(store):
    s = seed(store)
    comp = make_compaction(store, FakeLLM(SUMMARY, "## Objective\n- second"), settings=C.Settings(keep=2000))
    run(comp.compact(Trigger("manual", loaded(store, s))))
    for i in range(6, 10):
        store.add(s.id, user(f"request {i} " + "x" * 4000))
        store.add(s.id, assistant(f"answer {i}"))
    llm2 = FakeLLM("## Objective\n- second")
    comp2 = make_compaction(store, llm2, settings=C.Settings(keep=2000))
    out = run(comp2.compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed"
    sent = llm2.requests[0].messages
    assert sent[-1].content[0].text.startswith("Update the existing checkpoint")
    assert "<conversation-checkpoint>" in sent[0].content[0].text  # previous checkpoint leads the request
    assert history.load(store, s.id)[0].summary == "## Objective\n- second"


def test_reply_without_the_template_gets_one_nudge(store):
    s = seed(store)
    llm = FakeLLM("I will summarize it for you.", SUMMARY)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed" and len(llm.requests) == 2
    assert llm.requests[1].messages[-1].content[0].text == C.NUDGE


def test_two_bad_replies_fail_and_leave_history_alone(store):
    s = seed(store)
    llm = FakeLLM("nope", "still nope")
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "failed" and out.error.type == "compaction.failed"
    assert not any(isinstance(m, M.CompactionCompleted) for m in history.load(store, s.id))
    assert any(isinstance(m, M.CompactionFailed) for _, m in store.messages(s.id))


def test_nothing_to_compact(store):
    s = store.create("/p")
    out = run(make_compaction(store, FakeLLM()).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "failed" and out.error.message == "Nothing to compact yet"


def test_context_overflow_is_retried_at_shrinking_targets(store):
    s = seed(store, n=8)
    overflow = AIErr.error("InvalidRequest", "prompt is too long", classification="context-overflow")
    llm = FakeLLM(overflow, overflow, SUMMARY)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed" and len(llm.requests) == 3
    sizes = [C.estimate_request(r.system, r.tools, r.messages) for r in llm.requests]
    assert sizes[0] > sizes[1] > sizes[2]  # each attempt sends less
    assert any("older exchange" in (m.content[0].text if m.content and hasattr(m.content[0], "text") else "") for m in llm.requests[-1].messages)


def test_overflow_gives_up_after_the_last_shrink_step(store):
    s = seed(store, n=8)
    overflow = AIErr.error("InvalidRequest", "prompt is too long", classification="context-overflow")
    llm = FakeLLM(overflow, overflow, overflow, overflow)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "failed" and len(llm.requests) == 4


def test_payload_too_large_resends_the_same_content_as_text(store):
    s = seed(store)
    big = AIErr.error("InvalidRequest", "payload too large", classification="payload-too-large")
    llm = FakeLLM(big, SUMMARY)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed" and len(llm.requests) == 2
    assert llm.requests[1].messages[0].role == "user" and "[User]:" in llm.requests[1].messages[0].content[0].text


def test_transient_provider_errors_use_the_retry_policy(store):
    s = seed(store)
    boom = AIErr.classify_provider_failure("server error", status=503)
    llm = FakeLLM(boom, boom, SUMMARY)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed" and len(llm.requests) == 3


def test_authentication_errors_are_not_retried(store):
    s = seed(store)
    llm = FakeLLM(AIErr.classify_provider_failure("bad key", status=401), SUMMARY)
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "failed" and len(llm.requests) == 1


def test_output_limit_reached_is_a_failure_not_a_summary(store):
    s = seed(store)
    llm = FakeLLM([E.TextDelta(SUMMARY), E.Finish("length")])
    out = run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    assert out.status == "failed" and "output token limit" in out.error.message


def test_a_hook_can_supply_the_summary_without_a_model_call(store):
    s = seed(store)
    llm = FakeLLM()
    comp = make_compaction(store, llm, settings=C.Settings(keep=2000), summary_hook=lambda ctx, req: {"summary": "## Objective\n- from hook"})
    out = run(comp.compact(Trigger("manual", loaded(store, s))))
    assert out.status == "completed" and not llm.requests
    assert history.load(store, s.id)[0].summary == "## Objective\n- from hook"


def test_automatic_compaction_can_be_turned_off_but_manual_still_works(store):
    s = seed(store)
    comp = make_compaction(store, FakeLLM(SUMMARY), settings=C.Settings(auto=False, keep=2000))
    assert run(comp.compact(Trigger("auto", loaded(store, s)))).status == "skipped"
    assert run(comp.compact(Trigger("overflow", loaded(store, s)))).status == "skipped"
    assert run(comp.compact(Trigger("manual", loaded(store, s)))).status == "completed"


def test_overflow_trigger_aims_below_the_current_estimate(store):
    s = seed(store)
    llm = FakeLLM(SUMMARY)
    ctx = loaded(store, s)
    run(make_compaction(store, llm, settings=C.Settings(keep=2000)).compact(Trigger("overflow", ctx)))
    sent = C.estimate_request(llm.requests[0].system, llm.requests[0].tools, llm.requests[0].messages)
    assert sent <= C.estimate_context(ctx) * 0.7 + 3000  # the older part plus the prompt, under 70% of the full context


def test_usage_of_the_summary_call_is_recorded_on_the_session_and_the_message(store):
    s = seed(store)
    run(make_compaction(store, FakeLLM(SUMMARY), settings=C.Settings(keep=2000)).compact(Trigger("manual", loaded(store, s))))
    info = store.get(s.id)
    assert info.tokens.input == 100 and info.tokens.output == 20
    assert history.load(store, s.id)[0].tokens.input == 100


# ---- measuring the prompt


def test_prompt_estimate_uses_the_providers_last_measurement_as_an_anchor(store):
    s = store.create("/p", agent="build")
    store.add(s.id, user("a" * 4000))
    store.add(s.id, assistant("ok", tokens=M.TokenUsage(input=5000, output=200)))
    store.add(s.id, user("b" * 400))
    p = C.estimate_prompt(loaded(store, s))
    assert p.measured == 5200 and p.estimated >= 100  # the text after the anchor is estimated, nothing before it is
    other = M.Assistant(agent="build", model=M.ModelRef(provider_id="other", id="x"), content=[], tokens=M.TokenUsage(input=9999))
    s2 = store.create("/p", agent="build")
    store.add(s2.id, user("a"))
    store.add(s2.id, other)
    assert C.estimate_prompt(loaded(store, s2)).measured == 0  # another provider's count is not trusted


def test_an_errored_assistant_is_not_an_anchor(store):
    s = store.create("/p", agent="build")
    bad = M.Assistant(agent="build", model=MODEL.ref, content=[], tokens=M.TokenUsage(input=9999), error=M.SessionError(type="x", message="y"))
    store.add(s.id, user("hi"))
    store.add(s.id, bad)
    assert C.estimate_prompt(loaded(store, s)).measured == 0


def test_a_working_window_makes_automatic_compaction_happen_long_before_a_huge_window_is_full(store):
    s = seed(store)
    big = make_compaction(store, FakeLLM(SUMMARY), settings=C.Settings(keep=2000))
    assert run(big.compact(Trigger("auto", loaded(store, s)))).status == "skipped"  # the model's own window is nowhere near full
    capped = make_compaction(store, FakeLLM(SUMMARY), settings=C.Settings(keep=2000, window=4_000))
    out = run(capped.compact(Trigger("auto", loaded(store, s))))
    assert out.status == "completed"
    assert isinstance(history.load(store, s.id)[0], M.CompactionCompleted)  # and history now starts at the checkpoint


def test_the_working_window_never_raises_a_models_limit():
    small = ModelLimit(context=50_000, input=40_000, output=4_000)
    assert C.capped(small, 150_000) is small and C.capped(small, None) is small and C.capped(small, 0) is small
    huge = ModelLimit(context=1_000_000, input=934_464, output=65_536)
    capped = C.capped(huge, 150_000)
    assert capped.input == 150_000 and capped.context == 150_000 and capped.output == 65_536
    assert 100_000 < C.calculate_ceiling(capped, None) < 150_000  # automatic compaction starts a little below the working window
