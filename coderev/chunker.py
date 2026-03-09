"""AST-aware diff chunker.

Splits large diffs at function/class boundaries so each chunk
sent to a review agent contains complete, coherent code units.
"""

import re
from dataclasses import dataclass


@dataclass
class DiffChunk:
    """A single chunk of a diff, split at a safe boundary."""

    content: str
    file_paths: list[str]
    chunk_index: int
    total_chunks: int
    start_line: int
    end_line: int

    @property
    def is_single_chunk(self) -> bool:
        return self.total_chunks == 1


class ASTChunker:
    """Splits git diffs into chunks that respect Python AST boundaries.

    Falls back to heuristic splitting for non-Python files.

    Design principle: it is always better to include a little too much
    context in a chunk than to cut a function in half.
    """

    MAX_CHUNK_LINES = 300
    MAX_CHUNK_CHARS = 12_000

    def chunk(self, diff: str) -> list[DiffChunk]:
        """Split *diff* into a list of DiffChunk objects.

        If the diff is small enough, returns a single chunk.
        """
        lines = diff.split("\n")

        if len(lines) <= self.MAX_CHUNK_LINES:
            files = self._extract_files(diff)
            return [
                DiffChunk(
                    content=diff,
                    file_paths=files,
                    chunk_index=0,
                    total_chunks=1,
                    start_line=0,
                    end_line=len(lines),
                )
            ]

        return self._split_by_file_then_function(diff)

    # ── internal helpers ──────────────────────────────────────────────

    def _split_by_file_then_function(self, diff: str) -> list[DiffChunk]:
        file_sections = self._split_by_file(diff)
        raw_chunks: list[tuple[str, str]] = []

        for file_path, section in file_sections.items():
            section_line_count = section.count("\n")
            if file_path.endswith(".py") and section_line_count > self.MAX_CHUNK_LINES:
                sub_sections = self._split_python_at_boundaries(section, file_path)
                # If Python splitting didn't help (no boundaries found), fall back
                if len(sub_sections) == 1 and section_line_count > self.MAX_CHUNK_LINES:
                    sub_sections = self._split_by_lines(section, file_path)
                raw_chunks.extend(sub_sections)
            elif section_line_count > self.MAX_CHUNK_LINES:
                # Non-Python files: split by line count
                raw_chunks.extend(self._split_by_lines(section, file_path))
            else:
                raw_chunks.append((file_path, section))

        return self._pack_into_chunks(raw_chunks)

    def _split_by_file(self, diff: str) -> dict[str, str]:
        """Parse diff into ``{file_path: file_diff_section}``."""
        sections: dict[str, str] = {}
        current_file: str | None = None
        current_lines: list[str] = []

        for line in diff.split("\n"):
            match = re.match(r"^diff --git a/.+ b/(.+)$", line)
            if match:
                if current_file and current_lines:
                    sections[current_file] = "\n".join(current_lines)
                current_file = match.group(1)
                current_lines = [line]
            elif current_file:
                current_lines.append(line)

        if current_file and current_lines:
            sections[current_file] = "\n".join(current_lines)

        return sections

    def _split_python_at_boundaries(
        self, file_diff: str, file_path: str
    ) -> list[tuple[str, str]]:
        """Split a large Python file diff at function/class definition lines."""
        def_pattern = re.compile(r"^[+ ]( {0,8})(def |class |async def )", re.MULTILINE)
        lines = file_diff.split("\n")
        boundary_indices: list[int] = []

        for i, line in enumerate(lines):
            if def_pattern.match(line):
                boundary_indices.append(i)

        if not boundary_indices:
            return [(file_path, file_diff)]

        sections: list[tuple[str, str]] = []
        prev = 0
        for boundary in boundary_indices[1:]:
            section = "\n".join(lines[prev:boundary])
            if section.strip():
                sections.append((file_path, section))
            prev = boundary

        final = "\n".join(lines[prev:])
        if final.strip():
            sections.append((file_path, final))

        return sections if sections else [(file_path, file_diff)]

    def _split_by_lines(
        self, section: str, file_path: str
    ) -> list[tuple[str, str]]:
        """Fallback: split a section at MAX_CHUNK_LINES boundaries."""
        lines = section.split("\n")
        parts: list[tuple[str, str]] = []
        for i in range(0, len(lines), self.MAX_CHUNK_LINES):
            chunk_text = "\n".join(lines[i : i + self.MAX_CHUNK_LINES])
            if chunk_text.strip():
                parts.append((file_path, chunk_text))
        return parts if parts else [(file_path, section)]

    def _pack_into_chunks(
        self, sections: list[tuple[str, str]]
    ) -> list[DiffChunk]:
        """Greedy bin-pack sections into chunks within size limits."""
        chunks: list[tuple[str, list[str], int, int]] = []
        current_content: list[str] = []
        current_files: list[str] = []
        current_lines = 0
        current_chars = 0
        start_line = 0

        for file_path, section in sections:
            section_lines = section.count("\n")
            section_chars = len(section)

            if current_content and (
                current_lines + section_lines > self.MAX_CHUNK_LINES
                or current_chars + section_chars > self.MAX_CHUNK_CHARS
            ):
                chunks.append(
                    (
                        "\n".join(current_content),
                        list(set(current_files)),
                        start_line,
                        start_line + current_lines,
                    )
                )
                start_line += current_lines
                current_content = []
                current_files = []
                current_lines = 0
                current_chars = 0

            current_content.append(section)
            current_files.append(file_path)
            current_lines += section_lines
            current_chars += section_chars

        if current_content:
            chunks.append(
                (
                    "\n".join(current_content),
                    list(set(current_files)),
                    start_line,
                    start_line + current_lines,
                )
            )

        total = len(chunks)
        return [
            DiffChunk(
                content=content,
                file_paths=files,
                chunk_index=i,
                total_chunks=total,
                start_line=start_l,
                end_line=end_l,
            )
            for i, (content, files, start_l, end_l) in enumerate(chunks)
        ]

    def _extract_files(self, diff: str) -> list[str]:
        return re.findall(r"^diff --git a/.+ b/(.+)$", diff, re.MULTILINE)
