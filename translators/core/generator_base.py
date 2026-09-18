"""BaseGenerator — contract for target-language code generators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .ast import ProgramNode


@dataclass
class GeneratedFile:
    """One output file produced by a generator."""
    filename: str
    content: str
    language: str = ""  # e.g. "python", "java", "go"

    def write(self, output_dir: str | Path) -> Path:
        """Write this file to *output_dir* and return the written path."""
        out = Path(output_dir) / self.filename
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.content, encoding="utf-8")
        return out


class BaseGenerator(ABC):
    """Generate target-language source files from an AST.

    Subclass and implement :meth:`generate`.

    Example::

        class PythonGenerator(BaseGenerator):
            language = "python"

            def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
                ...
    """

    language: str = ""

    @abstractmethod
    def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
        """Translate *ast* into one or more output files."""

    def generate_to_dir(self, ast: ProgramNode, output_dir: str | Path) -> list[Path]:
        """Translate and write files to *output_dir*."""
        files = self.generate(ast)
        return [f.write(output_dir) for f in files]
