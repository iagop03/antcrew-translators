"""Translate Java source code to COBOL using an LLM, optionally guided by company standards."""
from __future__ import annotations

import concurrent.futures
import os
from typing import List, Optional

from polytranslate.utils.cobol_normalizer import COBOLNormalizer
from polytranslate.utils.cobol_standards_extractor import (
    COBOLStandards,
    COBOLStandardsExtractor,
    load_standards,
)
from polytranslate.utils.cobol_validator import COBOLValidator, ValidationResult
from polytranslate.utils.java_chunker import COBOLMerger, JavaChunk, JavaChunker

_LLM_TIMEOUT_SECONDS = 60
_CHUNK_THRESHOLD_LINES = 150


# ------------------------------------------------------------------
# Minimal LLM wrappers (no LangChain required)
# ------------------------------------------------------------------

class _AnthropicLLM:
    def __init__(self, model: str = "claude-sonnet-5", api_key: Optional[str] = None,
                 base_url: Optional[str] = None) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic") from None
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
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
    """Also used for OpenAI-compatible APIs: KeyBridge, DeepSeek, Groq, Ollama."""

    def __init__(self, model: str = "gpt-4o", api_key: Optional[str] = None,
                 base_url: Optional[str] = None) -> None:
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai") from None
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)
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


def _build_llm_from_env(model: Optional[str]) -> object:
    """Detect LLM config from environment variables.

    Priority:
      1. KEYBRIDGE_URL + KEYBRIDGE_TOKEN  (proxy — keys centralised)
      2. ANTHROPIC_API_KEY
      3. OPENAI_API_KEY
      4. DEEPSEEK_API_KEY                (OpenAI-compatible)
      5. GROQ_API_KEY                    (OpenAI-compatible)
    """
    kb_url = os.environ.get("KEYBRIDGE_URL", "").strip()
    kb_token = os.environ.get("KEYBRIDGE_TOKEN", "").strip()
    if kb_url and kb_token:
        return _OpenAILLM(
            model=model or "claude-sonnet-5",
            api_key=kb_token,
            base_url=kb_url.rstrip("/") + "/v1",
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _AnthropicLLM(model=model or "claude-sonnet-5")
    if os.environ.get("OPENAI_API_KEY"):
        return _OpenAILLM(model=model or "gpt-4o")
    if os.environ.get("DEEPSEEK_API_KEY"):
        return _OpenAILLM(
            model=model or "deepseek-chat",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com/v1",
        )
    if os.environ.get("GROQ_API_KEY"):
        return _OpenAILLM(
            model=model or "llama-3.3-70b-versatile",
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
    raise EnvironmentError(
        "No LLM configured. Set one of:\n"
        "  KEYBRIDGE_URL + KEYBRIDGE_TOKEN  (proxy — recommended for teams)\n"
        "  ANTHROPIC_API_KEY\n"
        "  OPENAI_API_KEY\n"
        "  DEEPSEEK_API_KEY\n"
        "  GROQ_API_KEY"
    )


# ------------------------------------------------------------------
# Translator
# ------------------------------------------------------------------

class JavaToCOBOLTranslator:
    """Translate Java code to COBOL, respecting company coding standards.

    Three ways to create:

    1. Auto-detect from environment (KeyBridge → Anthropic → OpenAI → DeepSeek → Groq)::

        translator = JavaToCOBOLTranslator.from_env()

    2. Bring your own LLM::

        translator = JavaToCOBOLTranslator(llm=ChatAnthropic(...))

    3. No LLM — for standards loading / prompt inspection only::

        translator = JavaToCOBOLTranslator()
        translator.load_standards("CLAIMS.cbl")
    """

    def __init__(self, llm=None, standards: Optional[COBOLStandards] = None,
                 chunk_threshold: int = _CHUNK_THRESHOLD_LINES) -> None:
        self.llm = llm
        self.standards = standards
        self.chunk_threshold = chunk_threshold
        self._chunker = JavaChunker(max_lines=chunk_threshold)
        self._merger = COBOLMerger()
        self._validator = COBOLValidator()

    @classmethod
    def from_env(cls, model: Optional[str] = None) -> "JavaToCOBOLTranslator":
        """Create a translator from environment variables.

        Detection order: KEYBRIDGE → ANTHROPIC → OPENAI → DEEPSEEK → GROQ
        """
        return cls(llm=_build_llm_from_env(model))

    # ------------------------------------------------------------------
    # Standards loaders
    # ------------------------------------------------------------------

    def load_standards_from_file(self, cobol_file: str) -> None:
        self.standards = COBOLStandardsExtractor().extract_from_file(cobol_file)

    def load_standards_from_doc(self, doc_file: str) -> None:
        self.standards = COBOLStandardsExtractor().extract_from_documentation(doc_file)

    def load_standards(self, source: str) -> None:
        self.standards = load_standards(source)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate(self, java_code: str, normalize: bool = True) -> str:
        """Translate *java_code* to COBOL.

        Args:
            java_code: Java source code string.
            normalize: Run COBOLNormalizer on the output (default True).

        Returns the COBOL string. Call ``validate(cobol)`` separately to
        check structural correctness.

        Raises ValueError if no LLM is configured.
        Raises TimeoutError if the LLM does not respond within 60 s.
        """
        if self.llm is None:
            raise ValueError(
                "An LLM must be provided to translate. "
                "Pass llm= at construction or use JavaToCOBOLTranslator.from_env()."
            )

        if self._chunker.should_chunk(java_code):
            cobol = self._translate_chunked(java_code)
        else:
            cobol = self._translate_single(java_code)

        if normalize:
            standards_dict = self.standards.to_dict() if self.standards else None
            cobol = COBOLNormalizer(standards=standards_dict).normalize(cobol)

        return cobol

    def validate(self, cobol: str) -> ValidationResult:
        """Validate the structural correctness of generated COBOL."""
        return self._validator.validate(cobol)

    def refine(self, java_code: str, current_cobol: str, feedback: str,
               normalize: bool = True) -> str:
        """Refine a previous translation based on user feedback.

        Args:
            java_code: Original Java source (for context).
            current_cobol: The COBOL output you want to improve.
            feedback: What's wrong / what to change.
            normalize: Run COBOLNormalizer on the result (default True).
        """
        if self.llm is None:
            raise ValueError("An LLM must be provided. Use from_env() or pass llm=.")

        prompt = self._build_refine_prompt(java_code, current_cobol, feedback)
        result_str = self._invoke(prompt)

        if normalize:
            standards_dict = self.standards.to_dict() if self.standards else None
            result_str = COBOLNormalizer(standards=standards_dict).normalize(result_str)

        return result_str

    # ------------------------------------------------------------------
    # Internal translation
    # ------------------------------------------------------------------

    def _translate_single(self, java_code: str) -> str:
        prompt = (
            self._build_prompt_with_standards(java_code)
            if self.standards
            else self._build_generic_prompt(java_code)
        )
        return self._invoke(prompt)

    def _translate_chunked(self, java_code: str) -> str:
        """Translate large Java file method-by-method, then merge."""
        chunks = self._chunker.chunk(java_code)
        cobol_parts: List[str] = []

        for chunk in chunks:
            cobol_parts.append(self._translate_chunk(chunk))

        return self._merger.merge(cobol_parts)

    def _translate_chunk(self, chunk: JavaChunk) -> str:
        prompt = self._build_chunk_prompt(chunk)
        return self._invoke(prompt)

    def _invoke(self, prompt: str) -> str:
        """Call LLM with hard timeout. Returns raw content string."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.llm.invoke, prompt)
            try:
                result = future.result(timeout=_LLM_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"LLM timed out after {_LLM_TIMEOUT_SECONDS}s. "
                    "Try again or use a faster model."
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

Standards:
- Working-storage variables: WS-* prefix, constants: WC-* prefix
- Paragraph names: ACTION-OBJECT pattern (e.g., CALCULATE-TOTAL)
- All uppercase with dashes, max 30 chars per name
- Use MOVE, PERFORM, COMPUTE, IF/END-IF

Java code:
```java
{java_code}
```

Output ONLY valid COBOL — no markdown fences or explanations.
Start with IDENTIFICATION DIVISION and end with STOP RUN."""

    def _build_chunk_prompt(self, chunk: JavaChunk) -> str:
        standards_text = (
            COBOLStandardsExtractor().to_prompt_instructions(self.standards)
            if self.standards
            else "Use WS- for variables, WC- for constants, ACTION-OBJECT for paragraphs."
        )
        return f"""You are a COBOL expert. You are translating a large Java class piece by piece.
This is {chunk.label()}.

{standards_text}

Translate ONLY the methods shown. Include all variable declarations needed for these methods.
This output will be merged with other chunks — do NOT add STOP RUN yet unless this is the last chunk.
{'This IS the last chunk — add STOP RUN at the end.' if chunk.is_last else 'This is NOT the last chunk — do NOT add STOP RUN.'}

Java code (chunk {chunk.index}/{chunk.total}):
```java
{chunk.code}
```

Output ONLY COBOL with all four divisions. No markdown fences."""

    def _build_refine_prompt(self, java_code: str, current_cobol: str, feedback: str) -> str:
        standards_text = (
            COBOLStandardsExtractor().to_prompt_instructions(self.standards)
            if self.standards
            else ""
        )
        standards_section = f"\n{standards_text}\n" if standards_text else ""
        return f"""You are a COBOL expert. You previously translated the following Java code to COBOL.
The user has reviewed your output and provided feedback. Produce an improved version.
{standards_section}
Original Java:
```java
{java_code}
```

Your previous COBOL translation:
```
{current_cobol}
```

User feedback: {feedback}

Produce a corrected COBOL version that addresses the feedback.
Output ONLY the COBOL code — no markdown fences, no explanations.
Start with IDENTIFICATION DIVISION and end with STOP RUN."""
