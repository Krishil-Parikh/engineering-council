"""Parity tests for the patch envelope and tool, ported from opencode's patch.test.ts and tool-patch.test.ts scenarios."""

import pytest

from harness.tool.builtin import patch as patch_tool
from harness.tool.info import ToolError
from harness.util import patch as P
from tests.harness.tools_rig import Rig


def wrap(body: str) -> str:
    return f"*** Begin Patch\n{body}\n*** End Patch"


def test_parses_add_update_delete():
    hunks = P.parse(wrap("*** Add File: a.txt\n+hello\n+world\n*** Update File: b.txt\n@@ ctx\n-old\n+new\n*** Delete File: c.txt"))
    assert [h.type for h in hunks] == ["add", "update", "delete"]
    assert hunks[0].contents == "hello\nworld"
    assert hunks[1].chunks[0].change_context == "ctx"
    assert hunks[1].chunks[0].old_lines == ["old"] and hunks[1].chunks[0].new_lines == ["new"]


def test_empty_patch_and_move():
    assert P.parse("*** Begin Patch\n*** End Patch") == []
    h = P.parse(wrap("*** Update File: a.txt\n*** Move to: b.txt\n@@\n-x\n+y"))[0]
    assert h.move_path == "b.txt"


def test_boundaries():
    with pytest.raises(P.BoundaryError, match="first line"):
        P.parse("nope\n*** End Patch")
    with pytest.raises(P.BoundaryError, match="last line"):
        P.parse("*** Begin Patch\n*** Add File: a\n+x")


def test_heredoc_wrappers():
    inner = wrap("*** Add File: a.txt\n+x")
    assert P.parse(f"cat <<'EOF'\n{inner}\nEOF")[0].path == "a.txt"
    assert P.parse(f"<<EOF\n{inner}\nEOF")[0].path == "a.txt"


def test_crlf_patch_lines_and_whitespace_headers():
    assert P.parse("*** Begin Patch\r\n  *** Add File: a.txt  \r\n+x\r\n*** End Patch  ")[0].contents == "x"


def test_invalid_hunks():
    with pytest.raises(P.InvalidHunkError, match="expected a line starting with '\\+'"):
        P.parse(wrap("*** Add File: a\nbad"))
    with pytest.raises(P.InvalidHunkError, match="Delete hunks do not contain body lines"):
        P.parse(wrap("*** Delete File: a\nbody"))
    with pytest.raises(P.InvalidHunkError, match="is empty"):
        P.parse(wrap("*** Update File: a"))
    with pytest.raises(P.InvalidHunkError, match="not a valid hunk header"):
        P.parse(wrap("*** Nope: a"))


def test_end_of_file_marker():
    h = P.parse(wrap("*** Update File: a\n@@\n-x\n+y\n*** End of File"))[0]
    assert h.chunks[0].end_of_file


def derive(original, body):
    return P.derive("f", P.parse(wrap("*** Update File: f\n" + body))[0].chunks, original)


def test_derive_multiple_chunks_and_trailing_newline():
    assert derive("a\nb\nc\nd", "@@\n a\n-b\n+B\n@@\n-d\n+D").content == "a\nB\nc\nD\n"


def test_derive_pure_addition_appends():
    assert derive("a\nb\n", "@@\n+c").content == "a\nb\nc\n"


def test_derive_change_context_disambiguates():
    assert derive("x\nfoo\ny\nx\nbar\n", "@@ y\n-x\n+X").content == "x\nfoo\ny\nX\nbar\n"


def test_derive_fuzzy_whitespace_and_unicode():
    assert derive("  a \nb\n", "@@\n-a\n+A").content == "A\nb\n"
    assert derive("say “hi”\n", '@@\n-say "hi"\n+bye').content == "bye\n"


def test_derive_preserves_bom():
    r = derive("﻿a\n", "@@\n-a\n+b")
    assert r.bom and r.content == "b\n"


def test_derive_missing_lines_and_blank():
    with pytest.raises(ValueError, match="Failed to find expected lines in f"):
        derive("a\n", "@@\n-zzz\n+y")
    with pytest.raises(ValueError, match="Failed to find context 'nope'"):
        derive("a\n", "@@ nope\n-a\n+b")


def test_eof_anchored_chunk_matches_from_the_end():
    assert derive("a\nx\na\nx\n", "@@\n-x\n+Y\n*** End of File").content == "a\nx\na\nY\n"


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path).add(patch_tool.make)


def test_tool_applies_add_update_delete_move(rig):
    rig.write("u.txt", "one\ntwo\n")
    rig.write("old.txt", "bye\n")
    rig.write("m.txt", "x\n")
    out = rig.text("patch", patchText=wrap(
        "*** Add File: new/a.txt\n+hi\n*** Update File: u.txt\n@@\n-two\n+2\n*** Delete File: old.txt\n*** Update File: m.txt\n*** Move to: moved.txt\n@@\n-x\n+y"
    ))
    assert out.splitlines() == ["Success. Updated the following files:", "A new/a.txt", "M u.txt", "D old.txt", "M moved.txt"]
    assert (rig.proj / "new" / "a.txt").read_text() == "hi\n"
    assert (rig.proj / "u.txt").read_text() == "one\n2\n"
    assert not (rig.proj / "old.txt").exists() and not (rig.proj / "m.txt").exists()
    assert (rig.proj / "moved.txt").read_text() == "y\n"


def test_tool_two_updates_to_one_file_compose(rig):
    rig.write("f.txt", "a\nb\n")
    rig.call("patch", patchText=wrap("*** Update File: f.txt\n@@\n-a\n+A\n*** Update File: f.txt\n@@\n-b\n+B"))
    assert (rig.proj / "f.txt").read_text() == "A\nB\n"


def test_tool_verification_failure_changes_nothing(rig):
    rig.write("f.txt", "a\n")
    with pytest.raises(ToolError, match="patch verification failed"):
        rig.call("patch", patchText=wrap("*** Add File: n.txt\n+x\n*** Update File: f.txt\n@@\n-zzz\n+y"))
    assert not (rig.proj / "n.txt").exists()


def test_tool_errors(rig):
    with pytest.raises(ToolError, match="patchText is required"):
        rig.call("patch", patchText="")
    with pytest.raises(ToolError, match="empty patch"):
        rig.call("patch", patchText="*** Begin Patch\n*** End Patch")
    with pytest.raises(ToolError, match="Failed to delete missing.txt: file does not exist"):
        rig.call("patch", patchText=wrap("*** Delete File: missing.txt"))
    with pytest.raises(ToolError, match="The first line"):
        rig.call("patch", patchText="garbage")


def test_tool_asks_one_edit_permission_for_all_files(tmp_path):
    from harness.schema.permission import Rule

    rig = Rig(tmp_path, rules=[Rule("*", "*", "allow"), Rule("edit", "*", "ask")], answers=["once"]).add(patch_tool.make)
    rig.call("patch", patchText=wrap("*** Add File: a.txt\n+1\n*** Add File: b.txt\n+2"))
    edits = [a for a in rig.asked if a[0] == "edit"]
    assert len(edits) == 1 and edits[0][1] == ["a.txt", "b.txt"]


def test_use_patch_model_selection():
    assert patch_tool.use_patch("gpt-5") and not patch_tool.use_patch("gpt-4o") and not patch_tool.use_patch("gpt-oss-20b")
    assert not patch_tool.use_patch("gemini-3-pro")
