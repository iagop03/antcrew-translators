"""COBOL source parser — produces a ProgramNode AST.

This is a structural parser: it understands COBOL's fixed-format layout and
major structural elements (DIVISIONS, SECTIONs, data items, paragraphs) but
does not evaluate expressions.  The goal is sufficient fidelity for code
generation, not a complete COBOL compiler front-end.

Fixed-format COBOL layout:
  Cols 1-6   : sequence number (ignored)
  Col  7     : indicator (* = comment, - = continuation, / = form-feed, D = debug)
  Cols 8-11  : Area A (division/section/paragraph names, level 01/77)
  Cols 12-72 : Area B (statements, subordinate data items)
  Cols 73+   : identification area (ignored)
"""
from __future__ import annotations

import re

from polytranslate.core.ast import (
    CallNode,
    DataItemNode,
    DivisionNode,
    IfNode,
    MoveNode,
    ParagraphNode,
    PerformNode,
    ProgramNode,
    SectionNode,
    StatementNode,
)
from polytranslate.core.parser_base import BaseParser

_DIVISION_RE   = re.compile(r"^\s*(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", re.I)
_SECTION_RE    = re.compile(r"^\s*(WORKING-STORAGE|FILE|LINKAGE|LOCAL-STORAGE|SCREEN)\s+SECTION", re.I)
_PROGRAM_ID_RE = re.compile(r"PROGRAM-ID\s*\.\s*([\w-]+)", re.I)
_AUTHOR_RE     = re.compile(r"AUTHOR\s*\.\s*(.+)", re.I)
_DATE_RE       = re.compile(r"DATE-WRITTEN\s*\.\s*(.+)", re.I)
_DATA_ITEM_RE  = re.compile(r"^\s*(\d{1,2})\s+([\w-]+)(.*)", re.I)
_PIC_RE        = re.compile(r"PIC(?:TURE)?(?:\s+IS)?\s+([\w()\-+.,/$V/Z*BPSE]+)", re.I)
_VALUE_RE      = re.compile(r"\bVALUE\s+(?:IS\s+)?['\"]?([^'\".\s]+)['\"]?", re.I)
_PARA_RE       = re.compile(r"^([A-Z][\w-]{0,29})\.$", re.I)
_MOVE_RE       = re.compile(r"\bMOVE\s+(.+?)\s+TO\s+([\w-]+)", re.I)
_CALL_RE       = re.compile(r"\bCALL\s+['\"]?([\w-]+)['\"]?(?:\s+USING\s+(.+))?", re.I)
_PERFORM_RE    = re.compile(r"\bPERFORM\s+([\w-]+)(?:\s+(.+))?", re.I)
_IF_RE         = re.compile(r"^\s*IF\s+(.+)", re.I)


def _strip_fixed(line: str) -> str:
    if len(line) >= 7:
        ind = line[6]
        if ind in ("*", "/", "D"):
            return ""
        return line[7:72].rstrip()
    return line.rstrip()


def _detect_free_format(lines: list[str]) -> bool:
    for line in lines[:30]:
        if len(line) >= 6 and line[:6].strip().isdigit():
            return False
        if re.match(r"^(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)", line.strip(), re.I):
            return True
    return False


class CobolParser(BaseParser):
    """Parse COBOL source text into a :class:`~translators.core.ast.ProgramNode`."""

    def parse(self, source: str, name: str = "") -> ProgramNode:
        raw_lines = source.splitlines()
        free = _detect_free_format(raw_lines)

        if free:
            code_lines = [ln for ln in raw_lines if not ln.strip().startswith("*>")]
        else:
            code_lines = [s for ln in raw_lines if (s := _strip_fixed(ln))]

        return self._build_ast(code_lines, name)

    def _build_ast(self, lines: list[str], name: str) -> ProgramNode:
        full = "\n".join(lines)

        # Top-level metadata
        pid_m = _PROGRAM_ID_RE.search(full)
        program_id = pid_m.group(1).rstrip(".") if pid_m else (name or "UNKNOWN")
        author_m = _AUTHOR_RE.search(full)
        date_m = _DATE_RE.search(full)

        prog = ProgramNode(
            program_id=program_id,
            author=author_m.group(1).strip() if author_m else "",
            date_written=date_m.group(1).strip() if date_m else "",
        )

        current_div: DivisionNode | None = None
        current_sec: SectionNode | None = None
        current_para: ParagraphNode | None = None
        in_procedure = False

        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()

            # Division boundary
            if m := _DIVISION_RE.match(stripped):
                div_name = m.group(1).upper()
                current_div = DivisionNode(name=div_name)
                prog.divisions.append(current_div)
                in_procedure = div_name == "PROCEDURE"
                current_sec = None
                current_para = None
                continue

            if current_div is None:
                continue

            # Section boundary
            if m := _SECTION_RE.match(stripped):
                sec_name = m.group(1).upper()
                current_sec = SectionNode(name=sec_name)
                current_div.sections.append(current_sec)
                current_para = None
                continue

            # DATA DIVISION — collect data items
            if current_div.name == "DATA" and current_sec:
                if m := _DATA_ITEM_RE.match(stripped):
                    level = int(m.group(1))
                    iname = m.group(2).upper()
                    rest = m.group(3)
                    pic = ""
                    if pm := _PIC_RE.search(rest):
                        pic = pm.group(1).upper()
                    value = ""
                    if vm := _VALUE_RE.search(rest):
                        value = vm.group(1)
                    item = DataItemNode(level=level, name=iname, pic=pic, value=value)
                    current_sec.items.append(item)
                continue

            # PROCEDURE DIVISION — paragraphs + statements
            if in_procedure:
                candidate = upper.rstrip(".")
                if (
                    re.match(r"^[A-Z][\w-]{0,29}$", candidate)
                    and upper.endswith(".")
                    and len(upper.split()) == 1
                    and candidate not in ("END-PROGRAM", "STOP", "EXIT")
                ):
                    current_para = ParagraphNode(name=candidate)
                    if current_sec:
                        current_sec.paragraphs.append(current_para)
                    else:
                        current_div.statements.append(current_para)  # type: ignore[arg-type]
                    continue

                stmt = self._parse_statement(stripped)
                if stmt:
                    if current_para:
                        current_para.statements.append(stmt)
                    elif current_div:
                        current_div.statements.append(stmt)

        return prog

    def _parse_statement(self, line: str) -> StatementNode | None:
        if m := _MOVE_RE.search(line):
            return MoveNode(raw=line, source=m.group(1).strip(), destination=m.group(2).strip())
        if m := _CALL_RE.search(line):
            using_raw = m.group(2) or ""
            using = [u.strip() for u in re.split(r"\s+", using_raw) if u.strip()]
            return CallNode(raw=line, target=m.group(1).strip(), using=using)
        if m := _PERFORM_RE.search(line):
            return PerformNode(raw=line, target=m.group(1).strip())
        if m := _IF_RE.search(line):
            return IfNode(raw=line, condition=m.group(1).strip())
        upper = line.strip().upper()
        if upper and not upper.startswith("END-") and not upper.startswith("*"):
            verb = upper.split()[0] if upper.split() else ""
            return StatementNode(verb=verb, raw=line)
        return None
