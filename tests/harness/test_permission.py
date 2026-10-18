"""Modelled on opencode packages/core/test/permission.test.ts."""

import asyncio

import pytest

from harness.permission import BlockedError, CorrectedError, DeclinedError, Permission, PermissionSaved, evaluate, merge
from harness.schema.permission import Rule
from harness.util import wildcard


def make(db, rules, observer=None, session_rules=None):
    return Permission(PermissionSaved(db, "proj"), lambda sid, agent: merge(rules, session_rules or []), observer)


def run(coro):
    return asyncio.run(coro)


# ---- wildcard and evaluate


def test_wildcards():
    assert wildcard.match("git status", "git status *") and wildcard.match("git status -s", "git status *")
    assert not wildcard.match("git statusx", "git status *")
    assert wildcard.match("src/a/b.py", "src/*") and wildcard.match("a/b/.env", "*.env") and not wildcard.match("a/b/.envx", "*.env")
    assert wildcard.match("a.b", "a.b") and not wildcard.match("axb", "a.b")  # regex specials are literal
    assert wildcard.match("C:\\repo\\file.txt", "C:/repo/*")  # Windows paths are slash-normalized
    assert wildcard.match("x", "?") and not wildcard.match("xy", "?")


def test_last_matching_rule_wins_and_nothing_matching_asks():
    rules = [Rule("*", "*", "allow"), Rule("bash", "git push *", "ask"), Rule("bash", "git push --force *", "deny")]
    assert evaluate("bash", "ls", rules).effect == "allow"
    assert evaluate("bash", "git push origin main", rules).effect == "ask"
    assert evaluate("bash", "git push --force origin main", rules).effect == "deny"
    assert evaluate("edit", "x", [Rule("bash", "*", "allow")]).effect == "ask"
    # a later ruleset overrides an earlier one
    assert evaluate("bash", "ls", [Rule("bash", "*", "deny")], [Rule("bash", "ls", "allow")]).effect == "allow"


# ---- the service


def test_ask_returns_the_effect_and_only_queues_prompts(db):
    async def go():
        p = make(db, [Rule("read", "*", "allow"), Rule("edit", "*", "ask"), Rule("bash", "rm *", "deny")])
        assert p.ask(session_id="s", action="read", resources=["a"])["effect"] == "allow" and p.list() == []
        assert p.ask(session_id="s", action="bash", resources=["rm -rf /"])["effect"] == "deny" and p.list() == []
        res = p.ask(session_id="s", action="edit", resources=["a.py"])
        assert res["effect"] == "ask" and [r.id for r in p.list()] == [res["id"]]

    run(go())


def test_assert_allows_and_blocks_without_asking(db):
    async def go():
        p = make(db, [Rule("*", "*", "allow"), Rule("bash", "rm *", "deny")])
        await p.assert_(session_id="s", action="read", resources=["a"])
        with pytest.raises(BlockedError) as e:
            await p.assert_(session_id="s", action="bash", resources=["ls", "rm -rf x"])  # one denied resource blocks the call
        assert e.value.permission == "bash"

    run(go())


def test_an_asked_permission_resolves_once_and_is_not_remembered(db):
    async def go():
        events = []
        p = make(db, [Rule("edit", "*", "ask")], observer=lambda k, d: events.append((k, d)))
        task = asyncio.create_task(p.assert_(session_id="s", action="edit", resources=["a.py"], save=["a.py"]))
        await asyncio.sleep(0)
        (req,) = p.list()
        p.reply(req.id, "once")
        await task
        assert p.list() == [] and PermissionSaved(db, "proj").list() == []
        assert [k for k, _ in events] == ["permission.asked", "permission.replied"]

    run(go())


def test_declined_and_corrected(db):
    async def go():
        p = make(db, [Rule("edit", "*", "ask")])
        t = asyncio.create_task(p.assert_(session_id="s", action="edit", resources=["a"]))
        await asyncio.sleep(0)
        p.reply(p.list()[0].id, "reject")
        with pytest.raises(DeclinedError):
            await t
        t = asyncio.create_task(p.assert_(session_id="s", action="edit", resources=["a"]))
        await asyncio.sleep(0)
        p.reply(p.list()[0].id, "reject", "use the tests folder")
        with pytest.raises(CorrectedError) as e:
            await t
        assert e.value.feedback == "use the tests folder"

    run(go())


def test_rejecting_one_request_rejects_the_whole_sessions_batch(db):
    async def go():
        p = make(db, [Rule("edit", "*", "ask")])
        a = asyncio.create_task(p.assert_(session_id="s1", action="edit", resources=["a"]))
        b = asyncio.create_task(p.assert_(session_id="s1", action="edit", resources=["b"]))
        c = asyncio.create_task(p.assert_(session_id="s2", action="edit", resources=["c"]))
        await asyncio.sleep(0)
        first = next(r for r in p.list() if r.resources == ["a"])
        p.reply(first.id, "reject", "stop")
        for t in (a, b):
            with pytest.raises(CorrectedError):
                await t
        assert not c.done() and len(p.list()) == 1  # another session is untouched
        p.reply(p.list()[0].id, "once")
        await c

    run(go())


def test_always_saves_the_pattern_and_approves_other_pending_requests_it_covers(db):
    async def go():
        p = make(db, [Rule("bash", "*", "ask")])
        a = asyncio.create_task(p.assert_(session_id="s", action="bash", resources=["git status"], save=["git status *"]))
        b = asyncio.create_task(p.assert_(session_id="s", action="bash", resources=["git status -s"]))
        c = asyncio.create_task(p.assert_(session_id="s", action="bash", resources=["npm test"]))
        await asyncio.sleep(0)
        first = next(r for r in p.list() if r.resources == ["git status"])
        p.reply(first.id, "always")
        await a
        await b  # covered by the saved pattern, approved without another question
        assert not c.done()
        assert PermissionSaved(db, "proj").list() == [Rule("bash", "git status *", "allow")]
        p.reply(p.list()[0].id, "reject")
        with pytest.raises(DeclinedError):
            await c
        # the saved approval now lets the same command through without asking
        await p.assert_(session_id="s", action="bash", resources=["git status --short"])

    run(go())


def test_saved_approvals_never_override_a_configured_deny(db):
    async def go():
        PermissionSaved(db, "proj").add("bash", ["rm *"])
        p = make(db, [Rule("bash", "*", "ask"), Rule("bash", "rm *", "deny")])
        with pytest.raises(BlockedError):
            await p.assert_(session_id="s", action="bash", resources=["rm -rf x"])

    run(go())


def test_session_rules_come_after_agent_rules(db):
    async def go():
        p = make(db, [Rule("edit", "*", "allow")], session_rules=[Rule("edit", "secret/*", "deny")])
        await p.assert_(session_id="s", action="edit", resources=["src/a.py"])
        with pytest.raises(BlockedError):
            await p.assert_(session_id="s", action="edit", resources=["secret/key"])

    run(go())


def test_closing_declines_everything_pending(db):
    async def go():
        p = make(db, [Rule("edit", "*", "ask")])
        t = asyncio.create_task(p.assert_(session_id="s", action="edit", resources=["a"]))
        await asyncio.sleep(0)
        p.close()
        with pytest.raises(DeclinedError):
            await t
        with pytest.raises(DeclinedError):
            await p.assert_(session_id="s", action="edit", resources=["a"])

    run(go())
