"""CobolASTMapper — normalise COBOL-specific AST idioms.

COBOL programs use implicit control flow (PERFORM, GOTO), implicit typing
(PIC clauses), and COBOL-specific data structures that target generators
need to map to their own type systems.

This mapper transforms a raw :class:`~translators.core.ast.ProgramNode`
produced by :class:`~translators.languages.cobol.parser.CobolParser` into
a normalised form that generators can consume without understanding COBOL
semantics.

Normalisation steps:
1.  Resolve PIC clauses → a canonical type descriptor
    ``{"base": "text|integer|decimal|binary", "length": int, "scale": int}``
2.  Flatten nested 01-level group items into a flat list with parent references
3.  Collect all paragraphs across sections into a single ordered list
4.  Mark entry point (first paragraph or ``MAIN-PARA`` / ``START-PARA``)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from polytranslate.core.ast import DataItemNode, ParagraphNode, ProgramNode, SectionNode


@dataclass
class NormalisedField:
    name: str
    cobol_pic: str
    base_type: str          # text | integer | decimal | binary | date | timestamp
    length: int
    scale: int
    nullable: bool
    parent: str = ""        # name of parent 01-level group, empty if top-level
    section: str = ""       # WORKING-STORAGE | LINKAGE | FILE | …


@dataclass
class NormalisedProgram:
    program_id: str
    author: str
    date_written: str
    fields: list[NormalisedField] = field(default_factory=list)
    paragraphs: list[ParagraphNode] = field(default_factory=list)
    entry_point: str = ""
    linkage_fields: list[NormalisedField] = field(default_factory=list)
    working_storage_fields: list[NormalisedField] = field(default_factory=list)


class CobolASTMapper:
    """Map a raw :class:`ProgramNode` to a :class:`NormalisedProgram`."""

    def map(self, program: ProgramNode) -> NormalisedProgram:
        norm = NormalisedProgram(
            program_id=program.program_id,
            author=program.author,
            date_written=program.date_written,
        )

        for div in program.divisions:
            for sec in div.sections:
                fields = self._map_section(sec)
                norm.fields.extend(fields)
                if sec.name in ("LINKAGE",):
                    norm.linkage_fields.extend(fields)
                elif sec.name in ("WORKING-STORAGE", "LOCAL-STORAGE"):
                    norm.working_storage_fields.extend(fields)
                norm.paragraphs.extend(sec.paragraphs)

            # Procedure paragraphs outside sections
            for stmt in div.statements:
                if isinstance(stmt, ParagraphNode):
                    norm.paragraphs.append(stmt)

        # Determine entry point
        ep_candidates = ("MAIN-PARA", "START-PARA", "BEGIN", "INIT")
        for para in norm.paragraphs:
            if para.name.upper() in ep_candidates:
                norm.entry_point = para.name
                break
        if not norm.entry_point and norm.paragraphs:
            norm.entry_point = norm.paragraphs[0].name

        return norm

    def _map_section(self, sec: SectionNode) -> list[NormalisedField]:
        fields: list[NormalisedField] = []
        current_parent = ""
        for item in sec.items:
            if item.level == 1:
                current_parent = item.name
            if item.pic:
                nf = self._map_item(item, parent=current_parent, section=sec.name)
                fields.append(nf)
        return fields

    def _map_item(self, item: DataItemNode, parent: str, section: str) -> NormalisedField:
        base, length, scale = _pic_to_type(item.pic)
        return NormalisedField(
            name=item.name,
            cobol_pic=item.pic,
            base_type=base,
            length=length,
            scale=scale,
            nullable=False,
            parent=parent,
            section=section,
        )


# ---------------------------------------------------------------------------
# PIC → type descriptor
# ---------------------------------------------------------------------------

def _pic_to_type(pic: str) -> tuple[str, int, int]:
    """Return (base_type, length, scale) from a COBOL PIC clause."""
    pic = pic.upper().strip()

    if not pic:
        return ("text", 1, 0)

    # Expand repeated notation: 9(5) → 99999, X(3) → XXX
    def expand(m: re.Match) -> str:
        char = m.group(1)
        count = int(m.group(2))
        return char * count

    expanded = re.sub(r"([A-Z9X\*Z$+\-])\((\d+)\)", expand, pic)

    if "V" in expanded or "." in expanded:
        # Decimal
        parts = re.split(r"V|\.", expanded, maxsplit=1)
        int_digits = len(re.findall(r"9", parts[0]))
        dec_digits = len(re.findall(r"9", parts[1])) if len(parts) > 1 else 0
        return ("decimal", int_digits + dec_digits, dec_digits)

    if re.search(r"^[S9\-+Z$*]+$", expanded):
        length = len(re.findall(r"9", expanded))
        return ("integer", length or 1, 0)

    if "COMP-2" in pic or "COMP-3" in pic or "COMP-4" in pic or "COMP" in pic:
        return ("binary", 8, 0)

    if expanded.startswith("X") or expanded.startswith("A"):
        length = len(expanded)
        return ("text", length, 0)

    return ("text", len(expanded) or 1, 0)
