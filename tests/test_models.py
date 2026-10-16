import pytest
from pydantic import ValidationError

from engineering_council.models import AcceptanceCriterion, Decision, DecisionSet, Requirement, normalize_id


def test_normalize_id():
    assert normalize_id("fr-1") == "FR-001"
    assert normalize_id(" NFR_12 ") == "NFR-012"
    assert normalize_id("nonsense") == "nonsense"


def test_requirement_id_is_normalised_and_validated():
    r = Requirement(id="fr-2", title="t", description="d", kind="FUNCTIONAL")
    assert r.id == "FR-002"
    with pytest.raises(ValidationError):
        Requirement(id="REQ-9", title="t", description="d", kind="FUNCTIONAL")


def test_criterion_requires_ac_id():
    with pytest.raises(ValidationError):
        AcceptanceCriterion(id="X-1", requirement_id="FR-001", given="g", when="w", then="t")


def _dec(i):
    return Decision(decision_id=i, statement="s", chosen_option="c", rationale="r", status="DECIDED")


def test_decision_set_rejects_duplicates_and_empty():
    with pytest.raises(ValidationError):
        DecisionSet(decisions=[_dec("DEC-001"), _dec("dec-1")])
    with pytest.raises(ValidationError):
        DecisionSet(decisions=[])
