"""Extract COBOL coding standards from existing source files or documentation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class COBOLStandards:
    """COBOL coding standards extracted from a source file or documentation."""

    var_prefixes: Dict[str, str]
    paragraph_pattern: str
    max_nesting_levels: int
    section_order: List[str]
    data_organization: str
    naming_style: str
    max_name_length: int
    examples: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "var_prefixes": self.var_prefixes,
            "paragraph_pattern": self.paragraph_pattern,
            "max_nesting_levels": self.max_nesting_levels,
            "section_order": self.section_order,
            "data_organization": self.data_organization,
            "naming_style": self.naming_style,
            "max_name_length": self.max_name_length,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "COBOLStandards":
        return cls(
            var_prefixes=data.get("var_prefixes", {}),
            paragraph_pattern=data.get("paragraph_pattern", "{ACTION}-{OBJECT}"),
            max_nesting_levels=data.get("max_nesting_levels", 2),
            section_order=data.get("section_order", ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]),
            data_organization=data.get("data_organization", "all_variables_at_top"),
            naming_style=data.get("naming_style", "UPPERCASE-WITH-DASHES"),
            max_name_length=data.get("max_name_length", 29),
            examples=data.get("examples", {}),
        )


_DEFAULT_PREFIXES: Dict[str, str] = {
    "working_storage": "WS",
    "constants": "WC",
    "linkage": "LK",
    "file": "FD",
}

_DEFAULT_SECTION_ORDER = ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]


class COBOLStandardsExtractor:
    """Extract naming and structural patterns from COBOL source or documentation."""

    def extract_from_file(self, cobol_file: str) -> COBOLStandards:
        """Read a .cbl/.cob/.cpy file and infer standards from its content."""
        text = Path(cobol_file).read_text(encoding="utf-8", errors="replace")

        var_prefixes = self._extract_var_prefixes(text)
        paragraphs = re.findall(r"^([A-Z][A-Z0-9-]{0,28})\.\s*$", text, re.MULTILINE)
        paragraph_pattern = self._infer_paragraph_pattern(paragraphs)
        max_nesting = self._detect_max_nesting(text)
        data_org = self._detect_data_organization(text)

        return COBOLStandards(
            var_prefixes=var_prefixes,
            paragraph_pattern=paragraph_pattern,
            max_nesting_levels=max_nesting,
            section_order=_DEFAULT_SECTION_ORDER,
            data_organization=data_org,
            naming_style="UPPERCASE-WITH-DASHES",
            max_name_length=29,
            examples={
                "variables": list(var_prefixes.keys())[:5],
                "paragraphs": paragraphs[:10],
            },
        )

    def extract_from_documentation(self, doc_file: str) -> COBOLStandards:
        """Parse a .md or .txt standards document and build a COBOLStandards object."""
        text = Path(doc_file).read_text(encoding="utf-8")

        ws_match = re.search(r"(?:Working storage|working-storage)[:\s]+(\w+[-]?)", text, re.IGNORECASE)
        wc_match = re.search(r"(?:Constants|Const)[:\s]+(\w+[-]?)", text, re.IGNORECASE)
        lk_match = re.search(r"(?:Linkage)[:\s]+(\w+[-]?)", text, re.IGNORECASE)
        pattern_match = re.search(r"(?:Paragraph Pattern|Pattern)[:\s]+(\{[^}]+\}[^$\n]*)", text, re.IGNORECASE)
        nesting_match = re.search(r"(?:Max Nesting|Nesting)[:\s]+(\d+)", text, re.IGNORECASE)

        def _strip(val: str) -> str:
            return val.rstrip("-").strip()

        return COBOLStandards(
            var_prefixes={
                "working_storage": _strip(ws_match.group(1)) if ws_match else "WS",
                "constants": _strip(wc_match.group(1)) if wc_match else "WC",
                "linkage": _strip(lk_match.group(1)) if lk_match else "LK",
                "file": "FD",
            },
            paragraph_pattern=pattern_match.group(1).strip() if pattern_match else "{ACTION}-{OBJECT}",
            max_nesting_levels=int(nesting_match.group(1)) if nesting_match else 2,
            section_order=_DEFAULT_SECTION_ORDER,
            data_organization="all_variables_at_top",
            naming_style="UPPERCASE-WITH-DASHES",
            max_name_length=29,
            examples={},
        )

    def to_prompt_instructions(self, standards: COBOLStandards) -> str:
        """Render a COBOLStandards object as LLM prompt instructions."""
        ws = standards.var_prefixes.get("working_storage", "WS")
        wc = standards.var_prefixes.get("constants", "WC")
        lk = standards.var_prefixes.get("linkage", "LK")
        fd = standards.var_prefixes.get("file", "FD")
        para_examples = ", ".join(standards.examples.get("paragraphs", [])[:5])

        return f"""COBOL Code Generation Standards:

Variable Naming:
- Working storage variables: {ws}-{{NAME}}
- Constants: {wc}-{{NAME}}
- Linkage section: {lk}-{{NAME}}
- File section: {fd}-{{NAME}}

Paragraph Naming:
- Pattern: {standards.paragraph_pattern}
- Each paragraph name should be ACTION-OBJECT (e.g., CALCULATE-ORDER-TOTAL)
- Examples: {para_examples or "VALIDATE-CLAIM, CALCULATE-TOTAL, PROCESS-ORDER"}

Structure Rules:
- Maximum nesting levels: {standards.max_nesting_levels}
- Data organization: All variables declared at top of WORKING-STORAGE
- Maximum name length: {standards.max_name_length} characters (COBOL limit)
- All names: UPPERCASE with dashes between words
- No abbreviations except standard (ID, QTY, AMT)"""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_var_prefixes(self, text: str) -> Dict[str, str]:
        matches = re.findall(r"01\s+([A-Z]+)-", text)
        prefixes: Dict[str, str] = {}
        for prefix in set(matches):
            if prefix == "WS":
                prefixes["working_storage"] = "WS"
            elif prefix == "WC":
                prefixes["constants"] = "WC"
            elif prefix == "LK":
                prefixes["linkage"] = "LK"
            elif prefix == "FD":
                prefixes["file"] = "FD"
        return prefixes or dict(_DEFAULT_PREFIXES)

    def _infer_paragraph_pattern(self, paragraphs: List[str]) -> str:
        if not paragraphs:
            return "{ACTION}-{OBJECT}"
        two_word = sum(1 for p in paragraphs if p.count("-") == 1)
        if two_word / len(paragraphs) > 0.6:
            return "{ACTION}-{OBJECT}"
        return "Free-form"

    def _detect_max_nesting(self, text: str) -> int:
        perform_lines = re.findall(r"^(\s*)PERFORM", text, re.MULTILINE)
        if not perform_lines:
            return 2
        max_indent = max(len(ln) for ln in perform_lines)
        return min(max(max_indent // 4, 2), 3)

    def _detect_data_organization(self, text: str) -> str:
        if "PROCEDURE DIVISION" in text:
            before_proc = text.split("PROCEDURE DIVISION")[0]
            if before_proc.count("01 WS-") > 0:
                return "all_variables_at_top"
        return "mixed"


def load_standards(source: Optional[str]) -> Optional[COBOLStandards]:
    """Convenience function: auto-detect file type and extract standards.

    Returns None when source is None.
    """
    if source is None:
        return None
    extractor = COBOLStandardsExtractor()
    path = Path(source)
    if path.suffix.lower() in {".cbl", ".cob", ".cpy", ".copy"}:
        return extractor.extract_from_file(source)
    return extractor.extract_from_documentation(source)
