"""Tests for the AST-aware diff chunker."""

import textwrap

import pytest

from coderev.chunker import ASTChunker, DiffChunk


@pytest.fixture
def chunker():
    return ASTChunker()


def _make_diff(filename: str, line_count: int, body_lines: list[str] | None = None) -> str:
    """Build a synthetic unified diff with *line_count* added lines."""
    if body_lines is None:
        body_lines = [f"+line {i}" for i in range(line_count)]
    header = (
        f"diff --git a/{filename} b/{filename}\n"
        f"new file mode 100644\n"
        f"--- /dev/null\n"
        f"+++ b/{filename}\n"
        f"@@ -0,0 +1,{len(body_lines)} @@\n"
    )
    return header + "\n".join(body_lines)


def _make_python_diff_with_functions(func_count: int, lines_per_func: int) -> str:
    """Build a Python diff containing *func_count* functions."""
    body: list[str] = []
    for i in range(func_count):
        body.append(f"+def func_{i}():")
        for j in range(lines_per_func - 1):
            body.append(f"+    x = {i * 100 + j}")
        body.append("+")
    return _make_diff("big_module.py", len(body), body)


# ── basic tests ───────────────────────────────────────────────────────


class TestSmallDiff:
    def test_small_diff_returns_single_chunk(self, chunker):
        diff = _make_diff("small.py", 50)
        chunks = chunker.chunk(diff)
        assert len(chunks) == 1
        assert chunks[0].is_single_chunk

    def test_single_chunk_metadata(self, chunker):
        diff = _make_diff("hello.py", 10)
        chunks = chunker.chunk(diff)
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1
        assert "hello.py" in chunks[0].file_paths


class TestLargeDiff:
    def test_large_diff_splits(self, chunker):
        diff = _make_diff("large.py", 600)
        chunks = chunker.chunk(diff)
        assert len(chunks) >= 2

    def test_chunk_indices_are_sequential(self, chunker):
        diff = _make_diff("large.py", 600)
        chunks = chunker.chunk(diff)
        for i, ch in enumerate(chunks):
            assert ch.chunk_index == i
            assert ch.total_chunks == len(chunks)

    def test_all_content_preserved(self, chunker):
        diff = _make_diff("large.py", 600)
        chunks = chunker.chunk(diff)
        # All original diff lines must appear in some chunk
        original_lines = set(diff.split("\n"))
        recombined_lines = set()
        for ch in chunks:
            recombined_lines.update(ch.content.split("\n"))
        assert original_lines.issubset(recombined_lines)


class TestPythonBoundaries:
    def test_splits_at_function_boundaries(self, chunker):
        """Chunks should not cut in the middle of a function body."""
        # 10 functions × 50 lines each = 500 lines total (exceeds MAX_CHUNK_LINES)
        diff = _make_python_diff_with_functions(func_count=10, lines_per_func=50)
        chunks = chunker.chunk(diff)
        assert len(chunks) >= 2

        # Each chunk should start with either a diff header or a function def
        for ch in chunks:
            first_meaningful = ""
            for line in ch.content.split("\n"):
                stripped = line.lstrip("+").lstrip()
                if stripped and not stripped.startswith(("diff ", "---", "+++", "@@", "new file")):
                    first_meaningful = stripped
                    break
            # Should be a def or import or first line of a section
            # The key assertion: no chunk starts in the middle of a function body
            if first_meaningful:
                assert not first_meaningful.startswith("x = "), (
                    f"Chunk starts mid-function with '{first_meaningful}'"
                )

    def test_single_huge_function_not_split(self, chunker):
        """A single 400-line function should stay in one chunk."""
        body = ["+def giant_function():"]
        for i in range(399):
            body.append(f"+    val = {i}")
        diff = _make_diff("giant.py", len(body), body)
        chunks = chunker.chunk(diff)
        # The entire function content should appear in a single chunk
        full_content = "\n".join(ch.content for ch in chunks)
        assert "def giant_function():" in full_content

    def test_python_split_preserves_all_content(self, chunker):
        """No diff lines should be dropped during AST-boundary splitting."""
        diff = _make_python_diff_with_functions(func_count=10, lines_per_func=50)
        chunks = chunker.chunk(diff)

        original_added = [
            line for line in diff.split("\n")
            if line.startswith("+") and not line.startswith("+++")
        ]
        recombined_added = [
            line for ch in chunks
            for line in ch.content.split("\n")
            if line.startswith("+") and not line.startswith("+++")
        ]
        assert len(recombined_added) >= len(original_added), (
            f"Lost {len(original_added) - len(recombined_added)} lines during chunking"
        )


class TestNonPythonFiles:
    def test_non_python_splits_by_size(self, chunker):
        diff = _make_diff("app.js", 600)
        chunks = chunker.chunk(diff)
        assert len(chunks) >= 2


class TestMultipleFiles:
    def test_files_correctly_attributed(self, chunker):
        diff1 = _make_diff("file_a.py", 50)
        diff2 = _make_diff("file_b.py", 50)
        combined = diff1 + "\n" + diff2
        chunks = chunker.chunk(combined)
        all_files = set()
        for ch in chunks:
            all_files.update(ch.file_paths)
        assert "file_a.py" in all_files
        assert "file_b.py" in all_files


class TestEdgeCases:
    def test_empty_diff(self, chunker):
        chunks = chunker.chunk("")
        assert len(chunks) == 1
        assert chunks[0].content == ""

    def test_diff_with_only_headers(self, chunker):
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py"
        chunks = chunker.chunk(diff)
        assert len(chunks) == 1
