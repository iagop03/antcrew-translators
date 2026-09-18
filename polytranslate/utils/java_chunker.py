"""Split large Java source files into method-level chunks for incremental translation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Lines per chunk before splitting is triggered
_DEFAULT_CHUNK_LINES = 150

# Matches a method signature at class body depth (brace depth == 1)
_METHOD_SIG_RE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|synchronized|abstract|native|default)\s+)*"
    r"(?:@\w+\s+)*"                    # optional annotation inline
    r"(?:[\w<>\[\],\s]+?\s+)"          # return type (greedy stopped by method name)
    r"(\w+)\s*\([^)]*\)"              # method name + params
    r"(?:\s+throws\s+[\w,\s]+)?"      # optional throws
    r"\s*\{",
    re.MULTILINE,
)

_FIELD_RE = re.compile(
    r"^[ \t]*(?:private|protected|public|static|final)\s+[\w<>\[\],\s]+\s+\w+\s*[;=]",
    re.MULTILINE,
)


@dataclass
class JavaChunk:
    """A translated-ready slice of a Java class."""

    code: str            # context header + method bodies for this chunk
    index: int           # 1-based position
    total: int           # total chunks produced from this file
    method_names: List[str]

    @property
    def is_first(self) -> bool:
        return self.index == 1

    @property
    def is_last(self) -> bool:
        return self.index == self.total

    def label(self) -> str:
        methods = ", ".join(self.method_names) or "unknown"
        return f"part {self.index}/{self.total} ({methods})"


class JavaChunker:
    """Split a Java class into method-sized slices.

    Each chunk carries a *context header* (class declaration + field
    declarations) so the LLM has the type information it needs to produce
    correct COBOL variable declarations for every chunk independently.

    Usage::

        chunker = JavaChunker()
        if chunker.should_chunk(java_code):
            chunks = chunker.chunk(java_code)
        else:
            chunks = [JavaChunk(code=java_code, index=1, total=1, method_names=[])]
    """

    def __init__(self, max_lines: int = _DEFAULT_CHUNK_LINES) -> None:
        self.max_lines = max_lines

    def should_chunk(self, java_code: str) -> bool:
        return len(java_code.splitlines()) > self.max_lines

    def chunk(self, java_code: str) -> List[JavaChunk]:
        """Return a list of chunks.  Always returns at least one chunk."""
        if not self.should_chunk(java_code):
            return [JavaChunk(code=java_code, index=1, total=1, method_names=[])]

        context = self._extract_context(java_code)
        method_blocks = self._extract_method_blocks(java_code)

        if not method_blocks:
            return self._chunk_by_lines(java_code, context)

        return self._group_methods(context, method_blocks)

    # ------------------------------------------------------------------

    def _extract_context(self, java_code: str) -> str:
        """Extract class declaration + field lines (skip method bodies)."""
        lines = java_code.splitlines()
        out: List[str] = []
        depth = 0

        for line in lines:
            stripped = line.strip()
            prev = depth
            depth += stripped.count("{") - stripped.count("}")

            # Inside a method body (depth >= 2): skip
            if depth >= 2 and prev >= 2:
                continue
            # Closing brace of a method
            if depth == 1 and prev == 2:
                continue

            out.append(line)

        return "\n".join(out)

    def _extract_method_blocks(self, java_code: str) -> List[Tuple[str, str]]:
        """Return [(method_name, full_source)] pairs."""
        lines = java_code.splitlines()
        blocks: List[Tuple[str, str]] = []
        i = 0

        while i < len(lines):
            m = _METHOD_SIG_RE.match(lines[i])
            if m:
                name = m.group(1)
                start = i
                depth = 0
                while i < len(lines):
                    depth += lines[i].count("{") - lines[i].count("}")
                    i += 1
                    if depth == 0:
                        break
                blocks.append((name, "\n".join(lines[start:i])))
            else:
                i += 1

        return blocks

    def _group_methods(self, context: str, method_blocks: List[Tuple[str, str]]) -> List[JavaChunk]:
        """Pack methods into chunks of ≤ max_lines each."""
        raw_chunks: List[Tuple[List[str], List[str]]] = []  # (lines, names)
        cur_lines: List[str] = []
        cur_names: List[str] = []

        for name, body in method_blocks:
            body_lines = body.splitlines()
            if cur_lines and len(cur_lines) + len(body_lines) > self.max_lines:
                raw_chunks.append((list(cur_lines), list(cur_names)))
                cur_lines, cur_names = [], []
            cur_lines.extend(body_lines)
            cur_names.append(name)

        if cur_lines:
            raw_chunks.append((cur_lines, cur_names))

        total = len(raw_chunks)
        chunks: List[JavaChunk] = []
        for idx, (body_lines, names) in enumerate(raw_chunks):
            code = context + f"\n// --- chunk {idx+1}/{total}: {', '.join(names)} ---\n" + "\n".join(body_lines)
            chunks.append(JavaChunk(code=code, index=idx + 1, total=total, method_names=names))

        return chunks

    def _chunk_by_lines(self, java_code: str, context: str) -> List[JavaChunk]:
        """Fallback when method detection fails: split by line count."""
        lines = java_code.splitlines()
        slices = [lines[i : i + self.max_lines] for i in range(0, len(lines), self.max_lines)]
        total = len(slices)
        return [
            JavaChunk(
                code=context + f"\n// --- chunk {idx+1}/{total} ---\n" + "\n".join(sl),
                index=idx + 1,
                total=total,
                method_names=[],
            )
            for idx, sl in enumerate(slices)
        ]


# ------------------------------------------------------------------
# COBOL merger
# ------------------------------------------------------------------

class COBOLMerger:
    """Combine COBOL programs produced from multiple Java chunks into one.

    Extracts WORKING-STORAGE variables and PROCEDURE DIVISION paragraphs
    from each chunk and assembles a single unified program.
    """

    _WS_RE = re.compile(
        r"WORKING-STORAGE\s+SECTION\.(.*?)(?=PROCEDURE\s+DIVISION|LINKAGE\s+SECTION|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    _PROC_RE = re.compile(r"PROCEDURE\s+DIVISION\.(.*?)$", re.DOTALL | re.IGNORECASE)
    _PROGRAM_ID_RE = re.compile(r"PROGRAM-ID\.\s*(\S+?)\.", re.IGNORECASE)
    # Matches a data item declaration: level + name (level 01/05/10/…, not 66/77/88)
    _DATA_ITEM_RE = re.compile(r"^\s*\d{1,2}\s+([A-Z][A-Z0-9-]+)", re.MULTILINE)

    def merge(self, chunks: List[str], program_id: Optional[str] = None) -> str:
        """Merge list of COBOL chunk outputs into one program."""
        if not chunks:
            return ""
        if len(chunks) == 1:
            return chunks[0]

        # Infer PROGRAM-ID from first chunk
        if program_id is None:
            m = self._PROGRAM_ID_RE.search(chunks[0])
            program_id = m.group(1).strip().rstrip(".") if m else "MERGED-PROGRAM"

        ws_sections: List[str] = []
        proc_sections: List[str] = []

        for chunk in chunks:
            ws_m = self._WS_RE.search(chunk)
            if ws_m:
                ws_sections.append(ws_m.group(1).strip())
            proc_m = self._PROC_RE.search(chunk)
            if proc_m:
                proc_sections.append(proc_m.group(1).strip())

        ws_body = self._deduplicate_ws(ws_sections) if ws_sections else "* No variables"
        proc_body = "\n".join(proc_sections) if proc_sections else "MAIN.\n    STOP RUN."

        return (
            f"IDENTIFICATION DIVISION.\n"
            f"PROGRAM-ID. {program_id}.\n\n"
            f"DATA DIVISION.\n"
            f"WORKING-STORAGE SECTION.\n"
            f"{ws_body}\n\n"
            f"PROCEDURE DIVISION.\n"
            f"{proc_body}\n"
        )

    def _deduplicate_ws(self, ws_sections: List[str]) -> str:
        """Merge WORKING-STORAGE sections, dropping duplicate variable names."""
        seen: set = set()
        output_lines: List[str] = []
        current_block: List[str] = []  # lines belonging to the current 01-group

        def flush_block() -> None:
            if not current_block:
                return
            # The first line of a block holds the top-level name
            m = self._DATA_ITEM_RE.match(current_block[0])
            name = m.group(1) if m else None
            if name is None or name not in seen:
                if name:
                    seen.add(name)
                output_lines.extend(current_block)
            current_block.clear()

        for section in ws_sections:
            for line in section.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("*"):
                    current_block.append(line)
                    continue
                # New top-level (01) item starts a new block
                if re.match(r"^\s*01\s+", line, re.IGNORECASE):
                    flush_block()
                current_block.append(line)

        flush_block()
        return "\n".join(output_lines) if output_lines else "* No variables"
