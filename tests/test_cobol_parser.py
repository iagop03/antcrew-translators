"""Tests for the COBOL parser and AST mapper."""
from __future__ import annotations

import textwrap

import pytest

from polytranslate.languages.cobol.parser import CobolParser
from polytranslate.languages.cobol.ast_mapper import CobolASTMapper, _pic_to_type


SAMPLE = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. SAMPLE.
    AUTHOR. TEST AUTHOR.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-NAME PIC X(30).
    01 WS-AMT  PIC 9(7)V99.
    LINKAGE SECTION.
    01 LK-FLAG PIC X(1).
    PROCEDURE DIVISION USING LK-FLAG.
    MAIN-PARA.
        MOVE SPACES TO WS-NAME
        PERFORM CALC-PARA
        STOP RUN.
    CALC-PARA.
        MOVE 0 TO WS-AMT
        STOP RUN.
""")


class TestCobolParser:
    def test_program_id(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        assert ast.program_id == "SAMPLE"

    def test_author(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        assert "TEST" in ast.author

    def test_divisions_present(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        names = {d.name for d in ast.divisions}
        assert "DATA" in names
        assert "PROCEDURE" in names

    def test_working_storage_fields(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        data_div = next(d for d in ast.divisions if d.name == "DATA")
        ws = next((s for s in data_div.sections if s.name == "WORKING-STORAGE"), None)
        assert ws is not None
        names = {i.name for i in ws.items}
        assert "WS-NAME" in names
        assert "WS-AMT" in names

    def test_paragraphs_detected(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        proc = next((d for d in ast.divisions if d.name == "PROCEDURE"), None)
        assert proc is not None
        all_paras = []
        for sec in proc.sections:
            all_paras.extend(sec.paragraphs)
        all_paras.extend(s for s in proc.statements if hasattr(s, "name"))
        para_names = {p.name for p in all_paras if hasattr(p, "name")}
        assert "MAIN-PARA" in para_names or "CALC-PARA" in para_names


class TestCobolASTMapper:
    def test_normalised_program_id(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        norm = CobolASTMapper().map(ast)
        assert norm.program_id == "SAMPLE"

    def test_working_storage_mapped(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        norm = CobolASTMapper().map(ast)
        ws_names = {f.name for f in norm.working_storage_fields}
        assert "WS-NAME" in ws_names

    def test_entry_point_detected(self) -> None:
        ast = CobolParser().parse(SAMPLE)
        norm = CobolASTMapper().map(ast)
        assert norm.entry_point in ("MAIN-PARA", "CALC-PARA", "")


class TestPicToType:
    def test_x_is_text(self) -> None:
        assert _pic_to_type("X(30)") == ("text", 30, 0)

    def test_9_is_integer(self) -> None:
        base, length, scale = _pic_to_type("9(7)")
        assert base == "integer"
        assert length == 7

    def test_decimal_has_scale(self) -> None:
        base, length, scale = _pic_to_type("9(7)V99")
        assert base == "decimal"
        assert scale == 2
