"""Parity tests for the file tools, ported from the scenarios in opencode's tool-read/edit/write/search tests."""

import pytest

from harness.schema.permission import Rule
from harness.tool.builtin import edit, read, search, write
from harness.tool.info import ToolError
from tests.harness.tools_rig import Rig


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path).add(read.make, edit.make, write.make, search.make_glob, search.make_grep)


def test_write_creates_then_overwrites(rig):
    assert "Created file successfully" in rig.text("write", path="a/b.txt", content="hi\n")
    assert (rig.proj / "a" / "b.txt").read_text() == "hi\n"
    assert "Wrote file successfully" in rig.text("write", path="a/b.txt", content="yo\n")


def test_write_preserves_bom(rig):
    rig.write("bom.txt", "﻿old\n")
    rig.text("write", path="bom.txt", content="new\n")
    assert (rig.proj / "bom.txt").read_bytes().startswith(b"\xef\xbb\xbf")


def test_edit_exact_replace(rig):
    rig.write("f.txt", "alpha\nbeta\n")
    assert "1 replacement" in rig.text("edit", path="f.txt", oldString="beta", newString="gamma")
    assert (rig.proj / "f.txt").read_text() == "alpha\ngamma\n"


def test_edit_replace_all_and_ambiguity(rig):
    rig.write("f.txt", "x x x")
    with pytest.raises(ToolError, match="Found 3 matches"):
        rig.call("edit", path="f.txt", oldString="x", newString="y")
    assert "3 replacements" in rig.text("edit", path="f.txt", oldString="x", newString="y", replaceAll=True)


def test_edit_missing_and_noop(rig):
    rig.write("f.txt", "abc")
    with pytest.raises(ToolError, match="Could not find"):
        rig.call("edit", path="f.txt", oldString="zzz", newString="q")
    with pytest.raises(ToolError, match="No changes"):
        rig.call("edit", path="f.txt", oldString="abc", newString="abc")


def test_edit_crlf_preserved(rig):
    rig.write("f.txt", "a\r\nb\r\nc\r\n")
    rig.call("edit", path="f.txt", oldString="b\nc", newString="B\nC")
    assert (rig.proj / "f.txt").read_bytes() == b"a\r\nB\r\nC\r\n"


def test_edit_unicode_typography_fallback(rig):
    rig.write("f.txt", "say “hello”\n")
    rig.call("edit", path="f.txt", oldString='say "hello"', newString="say bye")
    assert (rig.proj / "f.txt").read_text() == "say bye\n"


def test_edit_trailing_whitespace_fallback(rig):
    rig.write("f.txt", "one  \r\ntwo\r\n")
    rig.call("edit", path="f.txt", oldString="one\ntwo", newString="1\n2")
    assert (rig.proj / "f.txt").read_bytes() == b"1\r\n2\r\n"


def test_read_file_lines_and_paging(rig):
    rig.write("f.txt", "\n".join(f"l{i}" for i in range(1, 6)) + "\n")
    out = rig.text("read", path="f.txt")
    assert "1: l1" in out and "5: l5" in out
    page = rig.text("read", path="f.txt", offset=2, limit=2)
    assert "2: l2" in page and "3: l3" in page and "offset: 4" in page


def test_read_directory_listing(rig):
    rig.write("d/a.txt", "x")
    rig.write("d/sub/b.txt", "x")
    out = rig.text("read", path="d")
    assert out.splitlines()[1:] == ["sub/", "a.txt"]


def test_read_binary_rejected(rig):
    rig.write("b.bin", b"ab\x00cd", binary=True)
    with pytest.raises(ToolError, match="binary"):
        rig.call("read", path="b.bin")


def test_read_missing_suggests(rig):
    rig.write("notes.txt", "x")
    with pytest.raises(ToolError, match="Did you mean"):
        rig.call("read", path="note")


def test_read_alternate_path_recovery(rig):
    rig.write("Screen Shot.txt", "hello")
    out = rig.text("read", path="Screen Shot.txt")
    assert "1: hello" in out


def test_external_directory_requires_approval(tmp_path):
    rig = Rig(tmp_path, rules=[Rule("*", "*", "allow"), Rule("external_directory", "*", "ask")], answers=["once"]).add(read.make)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    out = rig.text("read", path=str(outside))
    assert "secret" in out
    assert any(a[0] == "external_directory" for a in rig.asked)


def test_glob_hidden_and_limit(rig):
    for n in ("a.ts", "b.ts", "c.ts"):
        rig.write(n, "")
    rig.write(".h/d.ts", "")
    res = rig.text("glob", pattern="**/*.ts", limit=2)
    assert "truncated" in res
    visible = rig.text("glob", pattern="**/*.ts")
    assert "d.ts" not in visible
    assert "d.ts" in rig.text("glob", pattern="**/*.ts", hidden=True)


def test_grep_matches_and_errors(rig):
    rig.write("a.txt", "foo\nbar\nfoo2\n")
    out = rig.text("grep", pattern="foo")
    assert "Found 2 matches" in out and "Line 3: foo2" in out
    assert "No matches found" in rig.text("grep", pattern="zzz")
    with pytest.raises(ToolError, match="Invalid regex"):
        rig.call("grep", pattern="(")
    assert "Found 1 matches" in rig.text("grep", pattern="bar", path="a.txt")
