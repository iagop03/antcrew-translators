"""Tests for Java→COBOL standards extractor and translator."""
from __future__ import annotations

import pytest

from polytranslate.translators.java_to_cobol import JavaToCOBOLTranslator
from polytranslate.utils.cobol_standards_extractor import COBOLStandardsExtractor


SAMPLE_COBOL = """
IDENTIFICATION DIVISION.
PROGRAM-ID. CLAIMS-PROCESSOR.

DATA DIVISION.
WORKING-STORAGE SECTION.
01 WC-MAX-AMOUNT PIC 9(7)V99 VALUE 99999.99.
01 WS-CLAIM-AMOUNT PIC 9(7)V99.
01 WS-CUSTOMER-ID PIC 9(8).
01 WS-STATUS-FLAG PIC X(2).

PROCEDURE DIVISION.
MAIN-PROCESS.
    PERFORM VALIDATE-CLAIM.
    PERFORM CALCULATE-TOTAL.
    STOP RUN.

VALIDATE-CLAIM.
    IF WS-CLAIM-AMOUNT > WC-MAX-AMOUNT
        MOVE "ER" TO WS-STATUS-FLAG
    END-IF.

CALCULATE-TOTAL.
    COMPUTE WS-CLAIM-AMOUNT = WS-CLAIM-AMOUNT * 1.21.
"""

SAMPLE_JAVA = """
public class OrderProcessor {
    private java.math.BigDecimal orderAmount;
    private static final java.math.BigDecimal MAX_AMOUNT = new java.math.BigDecimal("99999.99");
    private String customerId;

    public void processOrder() {
        validateOrder();
        calculateTotal();
    }

    private void validateOrder() {
        if (orderAmount.compareTo(MAX_AMOUNT) > 0) {
            // Handle error
        }
    }

    private void calculateTotal() {
        orderAmount = orderAmount.multiply(new java.math.BigDecimal("1.21"));
    }
}
"""


@pytest.fixture
def cobol_file(tmp_path):
    p = tmp_path / "claims.cbl"
    p.write_text(SAMPLE_COBOL)
    return str(p)


@pytest.fixture
def doc_file(tmp_path):
    content = """# COBOL Standards

## Variable Naming
- Working storage: WS-
- Constants: WC-
- Linkage: LK-

## Paragraph Pattern
{ACTION}-{OBJECT}

## Max Nesting
2
"""
    p = tmp_path / "standards.md"
    p.write_text(content)
    return str(p)


# ------------------------------------------------------------------
# COBOLStandardsExtractor
# ------------------------------------------------------------------

class TestExtractFromFile:
    def test_detects_ws_prefix(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.var_prefixes["working_storage"] == "WS"

    def test_detects_wc_prefix(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.var_prefixes["constants"] == "WC"

    def test_paragraph_pattern(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.paragraph_pattern == "{ACTION}-{OBJECT}"

    def test_paragraphs_in_examples(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert "VALIDATE-CLAIM" in s.examples.get("paragraphs", [])

    def test_max_nesting_gte_1(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.max_nesting_levels >= 1

    def test_section_order(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.section_order == ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]

    def test_max_name_length(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        assert s.max_name_length == 29


class TestExtractFromDoc:
    def test_ws_prefix(self, doc_file):
        s = COBOLStandardsExtractor().extract_from_documentation(doc_file)
        assert s.var_prefixes["working_storage"] == "WS"

    def test_wc_prefix(self, doc_file):
        s = COBOLStandardsExtractor().extract_from_documentation(doc_file)
        assert s.var_prefixes["constants"] == "WC"

    def test_paragraph_pattern(self, doc_file):
        s = COBOLStandardsExtractor().extract_from_documentation(doc_file)
        assert s.paragraph_pattern == "{ACTION}-{OBJECT}"

    def test_max_nesting(self, doc_file):
        s = COBOLStandardsExtractor().extract_from_documentation(doc_file)
        assert s.max_nesting_levels == 2


class TestToPromptInstructions:
    def test_contains_ws_prefix(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        prompt = COBOLStandardsExtractor().to_prompt_instructions(s)
        assert "WS-" in prompt

    def test_contains_wc_prefix(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        prompt = COBOLStandardsExtractor().to_prompt_instructions(s)
        assert "WC-" in prompt

    def test_contains_paragraph_pattern(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        prompt = COBOLStandardsExtractor().to_prompt_instructions(s)
        assert "{ACTION}-{OBJECT}" in prompt

    def test_contains_max_length(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        prompt = COBOLStandardsExtractor().to_prompt_instructions(s)
        assert "29" in prompt


# ------------------------------------------------------------------
# COBOLStandards serialisation
# ------------------------------------------------------------------

class TestStandardsRoundtrip:
    def test_to_dict_from_dict(self, cobol_file):
        s = COBOLStandardsExtractor().extract_from_file(cobol_file)
        d = s.to_dict()
        s2 = type(s).from_dict(d)
        assert s2.var_prefixes == s.var_prefixes
        assert s2.paragraph_pattern == s.paragraph_pattern
        assert s2.max_nesting_levels == s.max_nesting_levels


# ------------------------------------------------------------------
# JavaToCOBOLTranslator (no LLM needed for standards-loading tests)
# ------------------------------------------------------------------

class TestTranslatorStandardsLoading:
    def test_load_from_cobol_file(self, cobol_file):
        t = JavaToCOBOLTranslator()
        t.load_standards_from_file(cobol_file)
        assert t.standards is not None
        assert t.standards.var_prefixes["working_storage"] == "WS"

    def test_load_from_doc(self, doc_file):
        t = JavaToCOBOLTranslator()
        t.load_standards_from_doc(doc_file)
        assert t.standards is not None
        assert t.standards.max_nesting_levels == 2

    def test_load_standards_auto_detects_cobol(self, cobol_file):
        t = JavaToCOBOLTranslator()
        t.load_standards(cobol_file)
        assert t.standards is not None

    def test_translate_without_llm_raises(self):
        t = JavaToCOBOLTranslator()
        with pytest.raises(ValueError, match="LLM must be provided"):
            t.translate(SAMPLE_JAVA)

    def test_prompt_with_standards_contains_ws(self, cobol_file):
        t = JavaToCOBOLTranslator()
        t.load_standards_from_file(cobol_file)
        prompt = t._build_prompt_with_standards(SAMPLE_JAVA)
        assert "WS-" in prompt
        assert "COBOL" in prompt

    def test_generic_prompt_contains_ws(self):
        t = JavaToCOBOLTranslator()
        prompt = t._build_generic_prompt(SAMPLE_JAVA)
        assert "WS-" in prompt
        assert "COBOL" in prompt
