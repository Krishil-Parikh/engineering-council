from meetings import documents, synthesis
from meetings.models import Spec
from tests.meetings.fakes import decision_set, draft_spec


def make_spec() -> Spec:
    d = draft_spec()
    return synthesis.finalize_spec(Spec(**d.model_dump(), project_name="Todo CLI", decisions=[]), decision_set().decisions)


def test_prd_has_ids_and_gwt():
    prd = documents.render_prd(make_spec())
    for token in ("FR-001", "NFR-001", "AC-001", "**Given**", "**When**", "**Then**", "MVP Boundary"):
        assert token in prd


def test_technical_and_design_contents():
    s = make_spec()
    tech, design = documents.render_technical(s), documents.render_design(s)
    assert "Python 3.11" in tech and "DEC-001" in tech and "~~SQLite~~" in tech
    assert "def add_task(title: str) -> Task" in design and "todo/cli.py" in design and "Traceability" in design


def test_decisions_backfilled_with_requirements():
    assert make_spec().decisions[0].requirement_ids == ["FR-001", "FR-002", "NFR-001"]


def test_table_escapes_pipes():
    assert "a\\|b" in documents.table(["h"], [["a|b"]])
