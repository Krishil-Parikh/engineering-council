from engineering_council import documents, verification
from tests.test_documents import make_spec


def docs_for(spec):
    return {
        "PRD.md": documents.render_prd(spec),
        "Technical_Approach.md": documents.render_technical(spec),
        "Design.md": documents.render_design(spec),
    }


def run(spec, docs=None, formal=("DSP-001",)):
    return verification.verify(spec, list(formal), list(formal), docs or docs_for(spec))


def failed(report):
    return {c.name for c in report.failures}


def test_consistent_spec_passes():
    assert run(make_spec()).passed


def test_missing_document_fails():
    s = make_spec()
    d = docs_for(s)
    d["Design.md"] = ""
    assert "Required documents exist and are non-empty" in failed(run(s, d))


def test_invented_requirement_id_in_prose_fails():
    s = make_spec()
    d = docs_for(s)
    d["Technical_Approach.md"] += "\nSee FR-999 for details."
    assert "Ids mentioned in documents exist" in failed(run(s, d))


def test_functional_requirement_without_criteria_fails():
    s = make_spec()
    s = s.model_copy(update={"acceptance_criteria": [a for a in s.acceptance_criteria if a.requirement_id != "FR-002"]})
    assert "Every in-scope functional requirement has acceptance criteria" in failed(run(s))


def test_unaddressed_dispute_fails():
    assert "All CRITICAL/MAJOR disputes are resolved or explicitly unresolved" in failed(run(make_spec(), formal=("DSP-001", "DSP-002")))


def test_non_goal_listed_as_requirement_fails():
    s = make_spec()
    reqs = list(s.requirements)
    reqs[0] = reqs[0].model_copy(update={"title": "Cloud synchronisation across devices"})
    s = s.model_copy(update={"requirements": reqs})
    assert "Non-goals are not described as planned features" in failed(run(s))


def test_component_path_not_in_tree_fails():
    s = make_spec()
    comps = list(s.components)
    comps[1] = comps[1].model_copy(update={"path": "todo/missing.py"})
    s = s.model_copy(update={"components": comps})
    assert "API paths, entities and module paths are consistent" in failed(run(s))


def test_report_markdown_lists_failures():
    rep = run(make_spec(), formal=("DSP-001", "DSP-002"))
    md = verification.render_report(rep, ["note"])
    assert "FAILED" in md and "DSP-002" in md
