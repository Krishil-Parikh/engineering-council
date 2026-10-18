"""A2A over gRPC: direct questions, fan-out, group conversations, token auth, audit log."""

import asyncio
import json
import time

import grpc
import pytest

from council_a2a import A2AClient, A2AError, A2ANetwork, Inbound


async def echo(inb: Inbound) -> str:
    return f"{inb.recipient}|{inb.sender}|{inb.topic}|{inb.text}|{','.join(inb.group)}|{inb.context_id}"


def run(coro):
    return asyncio.run(coro)


def test_direct_question_carries_sender_topic_and_text():
    async def main():
        async with A2ANetwork() as net:
            await net.add("ana", echo, "backend developer", "BACKEND")
            reply = await net.ask("bob", "ana", "which db?", "storage")
            recipient, sender, topic, text, group, context = reply.split("|")
            assert (recipient, sender, topic, text, group) == ("ana", "bob", "storage", "which db?", "") and context
            assert net.directory()["ana"]["skill"] == "BACKEND" and net.directory()["ana"]["address"].startswith("127.0.0.1:")

    run(main())


def test_unknown_agent_is_a_clear_error():
    async def main():
        async with A2ANetwork() as net:
            await net.add("ana", echo)
            with pytest.raises(A2AError, match="no agent named 'zed'"):
                await net.ask("ana", "zed", "hi")

    run(main())


def test_handler_failure_comes_back_as_text_not_a_dead_connection():
    async def boom(inb):
        raise ValueError("kaboom")

    async def main():
        async with A2ANetwork() as net:
            await net.add("ana", boom)
            reply = await net.ask("bob", "ana", "x")
            assert reply == "(error: ValueError: kaboom)"
            assert await net.ask("bob", "ana", "again") == "(error: ValueError: kaboom)"  # the agent is still serving

    run(main())


def test_broadcast_runs_concurrently_shares_a_conversation_and_survives_a_dead_agent():
    contexts = []

    starts = {}

    async def slow(inb):
        contexts.append(inb.context_id)
        starts[inb.recipient] = time.monotonic()
        await asyncio.sleep(0.4)
        return inb.recipient

    async def main():
        async with A2ANetwork() as net:
            for n in ("a", "b", "c"):
                await net.add(n, slow)
            await net.agents["c"].stop()  # c goes away
            answers = await net.broadcast("s", ["a", "b", "c"], "ping", "t")
            assert answers["a"] == "a" and answers["b"] == "b" and answers["c"].startswith("(no answer:")
            assert abs(starts["a"] - starts["b"]) < 0.2  # the two live handlers ran at the same time
            assert len(set(contexts)) == 1  # one conversation

    run(main())


def test_group_conversation_shows_everyone_the_transcript():
    seen = []

    async def speak(inb):
        seen.append(inb.text)
        return f"{inb.recipient} agrees on round"

    async def main():
        async with A2ANetwork() as net:
            for n in ("ana", "bob"):
                await net.add(n, speak)
            transcript = await net.converse("db choice", ["ana", "bob"], "Which database?", rounds=2)
            assert [t.speaker for t in transcript] == ["system", "ana", "bob", "ana", "bob"]
            assert "Which database?" in seen[0] and "ana: ana agrees on round" in seen[1]  # bob saw ana's turn
            assert "Participants: ana, bob" in seen[0] and "round 2 of 2" in seen[2]
            early = await net.converse("t", ["ana", "bob"], "go", rounds=3, done=lambda tr: len(tr) >= 3)
            assert len(early) == 3

    run(main())


def test_token_is_required_when_configured():
    async def main():
        async with A2ANetwork(token="s3cret") as net:
            agent = await net.add("ana", echo)
            assert (await net.ask("bob", "ana", "hi")).startswith("ana|bob")
            for bad in (None, "wrong"):
                intruder = A2AClient("mallory", agent.address, bad)
                try:
                    with pytest.raises(A2AError):
                        await intruder.ask("let me in")
                finally:
                    await intruder.close()

    run(main())


def test_audit_log_records_every_exchange(tmp_path):
    async def main():
        log = tmp_path / "audit" / "a2a.jsonl"
        async with A2ANetwork(audit_path=log) as net:
            await net.add("ana", echo)
            await net.add("bob", echo)
            await net.ask("system", "ana", "q1", "plan")
            await net.broadcast("ana", ["bob"], "q2", "review")
            with pytest.raises(A2AError):
                await net.ask("ana", "ghost", "q3")
        lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
        assert [(l["sender"], l["recipient"], l["topic"]) for l in lines] == [("system", "ana", "plan"), ("ana", "bob", "review"), ("ana", "ghost", "")]
        assert all("reply" in l and l["ms"] >= 0 and l["context_id"] for l in lines[:2])
        assert "no agent named 'ghost'" in lines[2]["error"] and "reply" not in lines[2]

    run(main())


def test_the_same_agent_can_hold_many_conversations_at_once():
    async def slow(inb):
        await asyncio.sleep(0.3)
        return inb.text

    async def main():
        async with A2ANetwork() as net:
            await net.add("ana", slow)
            started = time.monotonic()
            replies = await asyncio.gather(*(net.ask(f"p{i}", "ana", str(i)) for i in range(5)))
            assert replies == ["0", "1", "2", "3", "4"] and time.monotonic() - started < 1.0

    run(main())
