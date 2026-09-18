"""Structural validator for LLM-generated COBOL code."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"  ERROR: {e}" for e in self.errors] + [f"  WARNING: {w}" for w in self.warnings]
        return "\n".join(lines) if lines else "  OK — all structural checks passed"


class COBOLValidator:
    """Quick structural validation for generated COBOL.

    Does NOT compile the code — checks for the most common LLM mistakes:
    missing divisions, markdown fences leaking into output, names too long,
    and missing STOP RUN.

    Usage::

        from polytranslate.utils.cobol_validator import COBOLValidator

        result = COBOLValidator().validate(cobol_code)
        if not result.valid:
            print(result.summary())
    """

    _DIVISION_RE = re.compile(r"\b(IDENTIFICATION|DATA|PROCEDURE)\s+DIVISION\b", re.IGNORECASE)
    _PROGRAM_ID_RE = re.compile(r"\bPROGRAM-ID\s*\.\s*\S+", re.IGNORECASE)
    _STOP_RUN_RE = re.compile(r"\bSTOP\s+RUN\b|\bGOBACK\b", re.IGNORECASE)
    _MARKDOWN_RE = re.compile(r"```")
    _LONG_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9-]{30,})\b")
    _LOWERCASE_PARA_RE = re.compile(r"^[a-z]\w*\.\s*$", re.MULTILINE)

    def validate(self, cobol: str) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        upper = cobol.upper()

        # Markdown fence leak (LLM wrapped output in a code block)
        if self._MARKDOWN_RE.search(cobol):
            errors.append("Output contains markdown fences (```) — strip them before use")

        # Required divisions
        found = {m.upper() for m in self._DIVISION_RE.findall(cobol)}
        for div in ("IDENTIFICATION", "DATA", "PROCEDURE"):
            if div not in found:
                errors.append(f"{div} DIVISION is missing")

        # PROGRAM-ID
        if not self._PROGRAM_ID_RE.search(cobol):
            errors.append("PROGRAM-ID not found")

        # STOP RUN / GOBACK
        if not self._STOP_RUN_RE.search(cobol):
            warnings.append("STOP RUN not found — program may not terminate")

        # WORKING-STORAGE SECTION
        if "WORKING-STORAGE SECTION" not in upper:
            warnings.append("WORKING-STORAGE SECTION missing — no variable declarations")

        # Name length (COBOL limit: 30 chars)
        long_names = self._LONG_NAME_RE.findall(cobol)
        if long_names:
            sample = ", ".join(long_names[:3])
            warnings.append(f"Names exceeding 30 chars (COBOL limit): {sample}")

        # Lowercase paragraph labels — LLM forgot to uppercase
        if self._LOWERCASE_PARA_RE.search(cobol):
            warnings.append("Lowercase paragraph labels found — run COBOLNormalizer to fix")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
