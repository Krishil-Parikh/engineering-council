import asyncio

from engineering_council import questions
from engineering_council.config import Settings
from engineering_council.models import HumanQuestion, QuestionCuration
from tests.fakes import FakeLLM


def q(text, opts=("Yes", "No"), default="No"):
    return HumanQuestion(question=text, why_it_matters="why", options=list(opts), recommended_default=default)


def test_cap_is_enforced_after_model_output():
    many = [q(f"Distinct topic number {chr(97 + i) * 6} budget?") for i in range(12)]
    assert len(questions.finalize(many, 5)) == 5


def test_dedupe_merges_near_duplicates():
    out = questions.dedupe([q("Should the first version support multiple tenants?"), q("Must the first version support multiple tenants?")])
    assert len(out) == 1 and out[0][1] == 2


def test_sanitize_adds_default_and_rejects_unanswerable():
    s = questions.sanitize(q("Pick one", opts=("A", "B"), default="C"))
    assert "C" in s.options and s.recommended_default == "C"
    assert questions.sanitize(q("Only one", opts=("A",), default="A")) is None


def test_curate_caps_and_survives_model_failure():
    s = Settings(max_questions=5)
    llm = FakeLLM()
    llm.overrides[QuestionCuration] = lambda p, st: QuestionCuration(questions=[q(f"Topic {chr(97 + i) * 7} scope?") for i in range(9)])
    cur, _ = asyncio.run(questions.curate(llm, [("A", q("x scope?"))], s, ""))
    assert len(cur.questions) <= 5
    cur2, note = asyncio.run(questions.curate(FakeLLM(fail_stages=("question_curation",)), [("A", q("Multi tenant support?"))], s, ""))
    assert len(cur2.questions) == 1 and "failed" in note


def test_ask_option_custom_default_and_non_interactive():
    qs = [q("One?"), q("Two?"), q("Three?")]
    replies = iter(["1", "3", "Maybe later", ""])
    out = questions.ask(qs, input_fn=lambda _: next(replies), output_fn=lambda _: None)
    assert [(a.answer, a.source) for a in out] == [("Yes", "option"), ("Maybe later", "custom"), ("No", "default")]
    auto = questions.ask(qs, interactive=False)
    assert all(a.source == "non_interactive_default" for a in auto)
