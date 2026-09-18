# polytranslate

Translate legacy code (COBOL) to Python, Java, or Go.

A three-stage pipeline: parse → normalise → generate. The translator is structural, not semantic — it produces a working skeleton with all data models and paragraphs mapped, which a developer then reviews and refines. Standalone library, zero runtime dependencies, works without antcrew.

---

## Install

```bash
pip install polytranslate
```

Requires Python 3.11+. No external dependencies for the core pipeline.

---

## Quick start

```python
from polytranslate.languages.cobol import CobolParser
from polytranslate.targets.python import PythonGenerator

# 1. Parse COBOL source
ast = CobolParser().parse_file("ORDPRC.cbl")

# 2. Generate Python
files = PythonGenerator().generate(ast)

# 3. Write output
for f in files:
    path = f.write("./output")
    print(f"Written: {path}")
```

This produces three files:

| File | Contents |
|---|---|
| `ordprc_model.py` | Dataclasses for WORKING-STORAGE and LINKAGE sections |
| `ordprc_logic.py` | Each COBOL paragraph → a Python method |
| `ordprc_runner.py` | Entry point that calls the first paragraph |

---

## CLI (via antcrew)

The `antcrew augment-cobol` command in the main `antcrew` package adds AI capabilities to COBOL programs without translating them. Use it when you want to keep the COBOL running and wrap it with Python AI:

```bash
antcrew augment-cobol ORDPRC.cbl --requirement "Add ML fraud scoring"
```

Use `antcrew-translators` when you want a full translation to Python/Java/Go.

---

## Architecture

```
COBOL source (.cbl / .cob / .cpy)
        │
        ▼
translators/languages/cobol/parser.py      ← CobolParser
        │  ProgramNode (AST)
        ▼
translators/languages/cobol/ast_mapper.py  ← CobolASTMapper
        │  NormalisedProgram
        ▼
translators/targets/{python,java,golang}/  ← Generator
        │  list[GeneratedFile]
        ▼
output files
```

### Core abstractions

**`ProgramNode`** — root of the AST. Contains `DivisionNode`, `SectionNode`, `DataItemNode`, `ParagraphNode`, and statement nodes (`MoveNode`, `CallNode`, `PerformNode`, `IfNode`).

**`CobolASTMapper`** — normalises the raw AST: resolves PIC clauses to `(base_type, length, scale)`, collects paragraphs across sections, identifies the entry point paragraph.

**`BaseParser`** / **`BaseGenerator`** — ABCs that define the contract for adding new source languages or target languages. One `parse()` method in, one `generate()` method out.

---

## Supported COBOL dialects

| Feature | Status |
|---|---|
| Fixed-format (.cbl, .cob) | ✅ |
| Free-format | ✅ |
| Copybooks (.cpy, .copy) | ✅ |
| WORKING-STORAGE / LINKAGE sections | ✅ |
| PIC clause type inference | ✅ |
| PERFORM / CALL / MOVE / IF | ✅ |
| EXEC CICS / EXEC SQL | ⚠️ detected, not translated |
| Report Writer | ❌ not supported |

---

## Adding a new target language

1. Create `polytranslate/targets/yourlang/generator.py`
2. Subclass `BaseGenerator` and implement `generate(ast: ProgramNode) -> list[GeneratedFile]`
3. Use `CobolASTMapper().map(ast)` to get a `NormalisedProgram` — it gives you typed fields, paragraphs, and the entry point without needing to understand COBOL PIC syntax

```python
from polytranslate.core.generator_base import BaseGenerator, GeneratedFile
from polytranslate.core.ast import ProgramNode
from polytranslate.languages.cobol.ast_mapper import CobolASTMapper

class RustGenerator(BaseGenerator):
    language = "rust"

    def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
        norm = CobolASTMapper().map(ast)
        # ... generate Rust from norm.fields, norm.paragraphs, etc.
        return [GeneratedFile("main.rs", content, language="rust")]
```

---

## Relationship to antcrew

`polytranslate` is a standalone library — zero runtime dependencies, works without antcrew. The `antcrew translate-cobol` CLI command uses it as an optional integration, but you can use polytranslate directly without any antcrew installation.

| Package | Purpose |
|---|---|
| `antcrew[legacy]` | Add AI to COBOL without rewriting — `COBOLAugment`, `AS400Connector`, `antcrew augment-cobol` CLI |
| `polytranslate` | Full COBOL → Python/Java/Go structural translation |

---

## License

MIT © Iago Pueyo
