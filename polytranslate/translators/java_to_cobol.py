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
    """Thin wrapper around the OpenAI SDK satisfying the .invoke() contract.

    Also used for OpenAI-compatible APIs: KeyBridge, DeepSeek, Groq, Ollama.
    """

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

    Priority order:
      1. KEYBRIDGE_URL + KEYBRIDGE_TOKEN  — proxy (all keys centralised in KeyBridge)
      2. ANTHROPIC_API_KEY               — Anthropic direct
      3. OPENAI_API_KEY                  — OpenAI direct
      4. DEEPSEEK_API_KEY                — DeepSeek direct (OpenAI-compatible)
      5. GROQ_API_KEY                    — Groq direct (OpenAI-compatible)

    Raises EnvironmentError when no option is configured.
    """
    kb_url = os.environ.get("KEYBRIDGE_URL", "").strip()
    kb_token = os.environ.get("KEYBRIDGE_TOKEN", "").strip()
    if kb_url and kb_token:
        # KeyBridge speaks both the Anthropic and OpenAI messages API.
        # Use the OpenAI-compatible path so a single _OpenAILLM handles any
        # model the proxy routes to (claude, gpt-4o, deepseek-chat, …).
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

    1. Auto-detect from environment (KeyBridge, Anthropic, OpenAI, DeepSeek, Groq)::

        translator = JavaToCOBOLTranslator.from_env()

    2. Bring your own LLM (LangChain-compatible or any object with .invoke())::

        translator = JavaToCOBOLTranslator(llm=ChatAnthropic(...))

    3. No LLM — useful for standards loading / prompt inspection only::

        translator = JavaToCOBOLTranslator()
        translator.load_standards("CLAIMS.cbl")
    """

    def __init__(self, llm=None, standards: Optional[COBOLStandards] = None) -> None:
        self.llm = llm
        self.standards = standards

    @classmethod
    def from_env(cls, model: Optional[str] = None) -> "JavaToCOBOLTranslator":
        """Create a translator from environment variables.

        Detection order:
          KEYBRIDGE_URL + KEYBRIDGE_TOKEN → Anthropic → OpenAI → DeepSeek → Groq

        Args:
            model: Override the default model name for the detected provider.
        """
        return cls(llm=_build_llm_from_env(model))

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
