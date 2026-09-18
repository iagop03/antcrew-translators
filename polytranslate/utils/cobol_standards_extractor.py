"""Extract COBOL coding standards from existing source files or documentation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Blocker #2: hard size cap to prevent memory issues on large COBOL corpora
_MAX_COBOL_SIZE = 50 * 1024 * 1024  # 50 MB

# Optimization #8: on-disk cache so the same file isn't re-extracted in every run
_CACHE_DIR = Path.home() / ".antcrew" / "standards"


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

    # Optimization #7: compile all patterns once at class level
    _VAR_PREFIX_RE = re.compile(r"01\s+([A-Z]+)-", re.MULTILINE)
    _PARAGRAPH_RE = re.compile(r"^([A-Z][A-Z0-9-]{0,28})\.\s*$", re.MULTILINE)
    _PERFORM_RE = re.compile(r"^(\s*)PERFORM", re.MULTILINE)
    _PROC_DIV_WS_RE = re.compile(r"01 WS-")
    _WS_RE = re.compile(r"(?:Working storage|working-storage)[:\s]+(\w+[-]?)", re.IGNORECASE)
    _WC_RE = re.compile(r"(?:Constants|Const)[:\s]+(\w+[-]?)", re.IGNORECASE)
    _LK_RE = re.compile(r"(?:Linkage)[:\s]+(\w+[-]?)", re.IGNORECASE)
    _PATTERN_RE = re.compile(r"(?:Paragraph Pattern|Pattern)[:\s]+(\{[^}]+\}[^$\n]*)", re.IGNORECASE)
    _NESTING_RE = re.compile(r"(?:Max Nesting|Nesting)[:\s]+(\d+)", re.IGNORECASE)

    def extract_from_file(self, cobol_file: str) -> COBOLStandards:
        """Read a .cbl/.cob/.cpy file and infer standards from its content."""
        # Blocker #2: validate before reading
        path = Path(cobol_file)
        if not path.exists():
            raise FileNotFoundError(f"COBOL file not found: {cobol_file}")
        stat = path.stat()
        if stat.st_size == 0:
            raise ValueError(f"COBOL file is empty: {cobol_file}")
        if stat.st_size > _MAX_COBOL_SIZE:
            raise ValueError(
                f"COBOL file too large ({stat.st_size / 1024 / 1024:.1f} MB > 50 MB): {cobol_file}"
            )

        # Optimization #8: return cached result if file hasn't changed
        cached = self._load_from_cache(path, stat.st_mtime)
        if cached is not None:
            return cached

        text = path.read_text(encoding="utf-8", errors="replace")

        var_prefixes = self._extract_var_prefixes(text)
        paragraphs = self._PARAGRAPH_RE.findall(text)
        paragraph_pattern = self._infer_paragraph_pattern(paragraphs)
        max_nesting = self._detect_max_nesting(text)
        data_org = self._detect_data_organization(text)

        result = COBOLStandards(
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
        self._save_to_cache(path, stat.st_mtime, result)
        return result

    def extract_from_documentation(self, doc_file: str) -> COBOLStandards:
        """Parse a .md or .txt standards document and build a COBOLStandards object."""
        text = Path(doc_file).read_text(encoding="utf-8")

        ws_match = self._WS_RE.search(text)
        wc_match = self._WC_RE.search(text)
        lk_match = self._LK_RE.search(text)
        pattern_match = self._PATTERN_RE.search(text)
        nesting_match = self._NESTING_RE.search(text)

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
        matches = self._VAR_PREFIX_RE.findall(text)
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
        """Blocker #5: detect 2-part vs 3-part vs free-form paragraph naming."""
        if not paragraphs:
            return "{ACTION}-{OBJECT}"

        total = len(paragraphs)
        part_counts = [p.count("-") + 1 for p in paragraphs]
        two_part = sum(1 for c in part_counts if c == 2)
        three_part = sum(1 for c in part_counts if c == 3)
        structured = two_part + three_part

        if two_part / total > 0.6:
            return "{ACTION}-{OBJECT}"
        if three_part / total > 0.4:
            return "{ACTION}-{OBJECT}-{QUALIFIER}"
        if structured / total > 0.5:
            return "{ACTION}-{OBJECT}-{QUALIFIER}" if three_part >= two_part else "{ACTION}-{OBJECT}"
        return "Free-form"

    def _detect_max_nesting(self, text: str) -> int:
        perform_lines = self._PERFORM_RE.findall(text)
        if not perform_lines:
            return 2
        max_indent = max(len(ln) for ln in perform_lines)
        return min(max(max_indent // 4, 2), 3)

    def _detect_data_organization(self, text: str) -> str:
        if "PROCEDURE DIVISION" in text:
            before_proc = text.split("PROCEDURE DIVISION")[0]
            if self._PROC_DIV_WS_RE.search(before_proc):
                return "all_variables_at_top"
        return "mixed"

    # ------------------------------------------------------------------
    # Cache helpers (Optimization #8)
    # ------------------------------------------------------------------

    def _cache_path(self, cobol_path: Path, mtime: float) -> Path:
        """Stable cache path keyed by filename + mtime (millisecond precision)."""
        key = f"{cobol_path.stem}_{int(mtime * 1000)}"
        return _CACHE_DIR / f"{key}.json"

    def _load_from_cache(self, cobol_path: Path, mtime: float) -> Optional[COBOLStandards]:
        try:
            cache = self._cache_path(cobol_path, mtime)
            if not cache.exists():
                return None
            data = json.loads(cache.read_text(encoding="utf-8"))
            return COBOLStandards.from_dict(data)
        except Exception:
            return None

    def _save_to_cache(self, cobol_path: Path, mtime: float, standards: COBOLStandards) -> None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = self._cache_path(cobol_path, mtime)
            cache.write_text(json.dumps(standards.to_dict()), encoding="utf-8")
        except Exception:
            pass  # caching is best-effort; never fail extraction


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
