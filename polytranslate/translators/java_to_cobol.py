"""Translate Java source code to COBOL using an LLM, optionally guided by company standards."""
from __future__ import annotations

import concurrent.futures
import os
from typing import Optional

from polytranslate.utils.cobol_standards_extractor import (
    COBOLStandards,
    COBOLStandardsExtractor,
    load_standards,
)

# Blocker #4: abort LLM calls that hang indefinitely
_LLM_TIMEOUT_SECONDS = 60


# ------------------------------------------------------------------
# Minimal LLM wrappers (no LangChain required)
# ------------------------------------------------------------------

class _AnthropicLLM:
    """Thin wrapper around the Anthropic SDK satisfying the .invoke() contract."""

    def __init__(self, model: str = "claude-sonnet-5") -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic") from None
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        self._model = model

    def invoke(self, prompt: str):
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        class _Result:
            content = msg.content[0].text

        return _Result()


class _OpenAILLM:
    """Thin wrapper around the OpenAI SDK satisfying the .invoke() contract."""

    def __init__(self, model: str = "gpt-4o") -> None:
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai") from None
        self._client = openai.OpenAI()  # reads OPENAI_API_KEY from env
        self._model = model

    def invoke(self, prompt: str):
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )

        class _Result:
            content = resp.choices[0].message.content

        return _Result()


# ------------------------------------------------------------------
# Translator
# ------------------------------------------------------------------

class JavaToCOBOLTranslator:
    """Translate Java code to COBOL, respecting company coding standards.

    Two ways to create:

    1. Bring your own LLM (LangChain-compatible or any object with .invoke())::

        translator = JavaToCOBOLTranslator(llm=ChatAnthropic(...))

    2. Auto-detect from environment (reads ANTHROPIC_API_KEY / OPENAI_API_KEY)::

        translator = JavaToCOBOLTranslator.from_env()
    """

    def __init__(self, llm=None, standards: Optional[COBOLStandards] = None) -> None:
        self.llm = llm
        self.standards = standards

    @classmethod
    def from_env(cls, model: Optional[str] = None) -> "JavaToCOBOLTranslator":
        """Create a translator using an API key from the environment.

        Checks ANTHROPIC_API_KEY first, then OPENAI_API_KEY.
        Raises EnvironmentError if neither is set.

        Args:
            model: Override the default model name. Pass e.g. ``"claude-opus-5"``
                   or ``"gpt-4o-mini"``. When omitted, uses ``claude-sonnet-5``
                   (Anthropic) or ``gpt-4o`` (OpenAI).
        """
        if os.environ.get("ANTHROPIC_API_KEY"):
            llm = _AnthropicLLM(model=model or "claude-sonnet-5")
        elif os.environ.get("OPENAI_API_KEY"):
            llm = _OpenAILLM(model=model or "gpt-4o")
        else:
            raise EnvironmentError(
                "No LLM API key found in the environment.\n"
                "Set one of:\n"
                "  export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  export OPENAI_API_KEY=sk-..."
            )
        return cls(llm=llm)

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
                "Pass llm= at construction or use JavaToCOBOLTranslator.from_env()."
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
