"""Tests for Java and Go generators."""
from __future__ import annotations

import textwrap

import pytest

from translators.languages.cobol.parser import CobolParser
from translators.targets.java import JavaGenerator
from translators.targets.golang import GoGenerator

SAMPLE = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ORDPRC.
    AUTHOR. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-ORDER-ID   PIC 9(10).
    01 WS-AMOUNT     PIC 9(7)V99.
    01 WS-STATUS     PIC X(2).
    LINKAGE SECTION.
    01 LK-FLAG       PIC X(1).
    PROCEDURE DIVISION USING LK-FLAG.
    MAIN-PARA.
        MOVE 0 TO WS-ORDER-ID
        PERFORM VALIDATE-PARA
        STOP RUN.
    VALIDATE-PARA.
        MOVE "OK" TO WS-STATUS
        STOP RUN.
""")


@pytest.fixture
def ast():
    return CobolParser().parse(SAMPLE)


# ---------------------------------------------------------------------------
# JavaGenerator
# ---------------------------------------------------------------------------

class TestJavaGenerator:
    def test_produces_three_files(self, ast) -> None:
        files = JavaGenerator().generate(ast)
        names = {f.filename for f in files}
        assert "OrdprcData.java" in names
        assert "Ordprc.java" in names
        assert "OrdprcRunner.java" in names

    def test_data_file_has_fields(self, ast) -> None:
        files = {f.filename: f for f in JavaGenerator().generate(ast)}
        data = files["OrdprcData.java"].content
        assert "wsOrderId" in data or "WsOrderId" in data or "WS_ORDER_ID" in data or "wsOrderId" in data.lower()
        assert "private" in data

    def test_data_file_has_getters_setters(self, ast) -> None:
        files = {f.filename: f for f in JavaGenerator().generate(ast)}
        data = files["OrdprcData.java"].content
        assert "get" in data.lower()
        assert "set" in data.lower()

    def test_logic_file_has_paragraphs(self, ast) -> None:
        files = {f.filename: f for f in JavaGenerator().generate(ast)}
        logic = files["Ordprc.java"].content
        assert "mainPara" in logic or "MainPara" in logic
        assert "validatePara" in logic or "ValidatePara" in logic

    def test_runner_has_main(self, ast) -> None:
        files = {f.filename: f for f in JavaGenerator().generate(ast)}
        runner = files["OrdprcRunner.java"].content
        assert "public static void main(String[] args)" in runner
        assert "Ordprc" in runner

    def test_package_configurable(self, ast) -> None:
        files = JavaGenerator(package="com.acme.batch").generate(ast)
        assert all("com.acme.batch" in f.content for f in files)

    def test_language_attribute(self) -> None:
        assert JavaGenerator.language == "java"

    def test_all_files_have_java_language(self, ast) -> None:
        files = JavaGenerator().generate(ast)
        assert all(f.language == "java" for f in files)


# ---------------------------------------------------------------------------
# GoGenerator
# ---------------------------------------------------------------------------

class TestGoGenerator:
    def test_produces_three_files(self, ast) -> None:
        files = GoGenerator().generate(ast)
        names = {f.filename for f in files}
        assert "ordprc_data.go" in names
        assert "ordprc_logic.go" in names
        assert "ordprc_main.go" in names

    def test_data_file_has_struct(self, ast) -> None:
        files = {f.filename: f for f in GoGenerator().generate(ast)}
        data = files["ordprc_data.go"].content
        assert "type WorkingStorage struct" in data
        assert "type Ordprc struct" in data

    def test_data_file_has_fields(self, ast) -> None:
        files = {f.filename: f for f in GoGenerator().generate(ast)}
        data = files["ordprc_data.go"].content
        assert "WsOrderId" in data or "WsAmount" in data or "WsStatus" in data

    def test_data_has_constructor(self, ast) -> None:
        files = {f.filename: f for f in GoGenerator().generate(ast)}
        data = files["ordprc_data.go"].content
        assert "func NewOrdprc()" in data

    def test_logic_file_has_paragraphs(self, ast) -> None:
        files = {f.filename: f for f in GoGenerator().generate(ast)}
        logic = files["ordprc_logic.go"].content
        assert "func (p *Ordprc) MainPara()" in logic
        assert "func (p *Ordprc) ValidatePara()" in logic

    def test_main_file_calls_entry(self, ast) -> None:
        files = {f.filename: f for f in GoGenerator().generate(ast)}
        main = files["ordprc_main.go"].content
        assert "func main()" in main
        assert "NewOrdprc()" in main

    def test_language_attribute(self) -> None:
        assert GoGenerator.language == "go"

    def test_all_files_have_go_language(self, ast) -> None:
        files = GoGenerator().generate(ast)
        assert all(f.language == "go" for f in files)

    def test_package_name_from_program_id(self, ast) -> None:
        files = GoGenerator().generate(ast)
        assert all(f.content.startswith("package ordprc") for f in files)


# ---------------------------------------------------------------------------
# GeneratedFile.write()
# ---------------------------------------------------------------------------

class TestGeneratedFileWrite:
    def test_write_creates_file(self, ast, tmp_path) -> None:
        files = JavaGenerator().generate(ast)
        for f in files:
            written = f.write(tmp_path)
            assert written.exists()
            assert written.read_text(encoding="utf-8") == f.content

    def test_write_go_creates_file(self, ast, tmp_path) -> None:
        files = GoGenerator().generate(ast)
        for f in files:
            written = f.write(tmp_path)
            assert written.exists()
