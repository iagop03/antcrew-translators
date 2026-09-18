"""Translate Java source code to COBOL using an LLM, optionally guided by company standards."""
from __future__ import annotations

import concurrent.futures
from typing import Optional

from polytranslate.utils.cobol_standards_extractor import (
    COBOLStandards,
    COBOLStandardsExtractor,
    load_standards,
)

# Blocker #4: abort LLM calls that hang indefinitely
_LLM_TIMEOUT_SECONDS = 60


class JavaToCOBOLTranslator:
    """Translate Java code to COBOL, respecting company coding standards."""

    def __init__(self, llm=None, standards: Optional[COBOLStandards] = None) -> None:
        self.llm = llm
        self.standards = standards

    # ------------------------------------------------------------------
    # Standards loaders
    # ------------------------------------------------------------------

    def load_standards_from_file(self, cobol_file: str) -> None:
        """Extract standards from an existing .cbl/.cob/.cpy file."""
        self.standards = COBOLStandardsExtractor().extract_from_file(cobol_file)

    def load_standards_from_doc(self, doc_file: str) -> None:
        """Extract standards from a .md/.txt documentation file."""
        self.standards = COBOLStandardsExtractor().extract_from_documentation(doc_file)

    def load_standards(self, source: str) -> None:
        """Auto-detect file type and load standards (COBOL source or doc)."""
        self.standards = load_standards(source)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate(self, java_code: str) -> str:
        """Translate *java_code* to COBOL.

        Raises ValueError when no LLM is configured.
        Raises TimeoutError when the LLM does not respond within 60 seconds.
        """
        if self.llm is None:
            raise ValueError(
                "An LLM must be provided to translate. "
                "Pass llm= at construction or call translator.llm = build_llm('claude')."
            )

        prompt = (
            self._build_prompt_with_standards(java_code)
            if self.standards
            else self._build_generic_prompt(java_code)
        )

        # Blocker #4: wrap LLM call with a hard timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.llm.invoke, prompt)
            try:
                result = future.result(timeout=_LLM_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"Translation timed out after {_LLM_TIMEOUT_SECONDS}s. "
                    "The LLM API may be overloaded — try again or use a different model."
                ) from None

        return result.content if hasattr(result, "content") else str(result)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_prompt_with_standards(self, java_code: str) -> str:
        standards_text = COBOLStandardsExtractor().to_prompt_instructions(self.standards)
        return f"""You are a COBOL expert specialising in migrating Java code to legacy COBOL systems.

{standards_text}

IMPORTANT:
- Follow the naming conventions above EXACTLY (WS-, WC-, etc.)
- Use the paragraph pattern specified above
- Organise variables according to the structure rules
- Use proper COBOL idioms (MOVE, PERFORM, COMPUTE, IF/END-IF)
- Include brief comments explaining non-obvious logic

Java code to convert:
```java
{java_code}
```

Generate COBOL code that:
1. Is functionally equivalent to the Java code
2. Follows all the standards listed above
3. Is ready to integrate with existing COBOL systems
4. Uses proper COBOL syntax and all four divisions

Output ONLY the COBOL code — no markdown fences, no explanations, no backticks.
Start with IDENTIFICATION DIVISION and end with STOP RUN."""

    def _build_generic_prompt(self, java_code: str) -> str:
        return f"""You are a COBOL expert. Convert the following Java code to COBOL.

Follow these general COBOL standards:
- Working-storage variables: WS-* prefix
- Constants: WC-* prefix
- Paragraph names: ACTION-OBJECT pattern (e.g., CALCULATE-TOTAL)
- All uppercase with dashes between words
- Max 29 characters for names
- Use MOVE, PERFORM, COMPUTE, IF/END-IF idioms

Java code to convert:
```java
{java_code}
```

Generate COBOL code that:
1. Is functionally equivalent to the Java code
2. Uses proper COBOL syntax and all four divisions
3. Includes helpful comments

Output ONLY the COBOL code — no markdown fences or explanations.
Start with IDENTIFICATION DIVISION and end with STOP RUN."""
