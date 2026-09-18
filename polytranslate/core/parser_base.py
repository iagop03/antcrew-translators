"""BaseParser — contract for language-specific parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .ast import ProgramNode


class ParseError(Exception):
    """Raised when a source file cannot be parsed."""

    def __init__(self, message: str, line: int = 0, source: str = "") -> None:
        super().__init__(message)
        self.line = line
        self.source = source

    def __str__(self) -> str:
        loc = f" (line {self.line})" if self.line else ""
        src = f" in {self.source}" if self.source else ""
        return f"{super().__str__()}{loc}{src}"


class BaseParser(ABC):
    """Parse a source file into a :class:`~translators.core.ast.ProgramNode`.

    Subclass and implement :meth:`parse`.  Use :meth:`parse_file` to handle
    I/O and encoding uniformly.

    Example::

        class CobolParser(BaseParser):
            def parse(self, source: str, name: str = "") -> ProgramNode:
                ...
    """

    @abstractmethod
    def parse(self, source: str, name: str = "") -> ProgramNode:
        """Parse *source* text into an AST.

        Parameters
        ----------
        source:
            Full source text of the file.
        name:
            Optional display name used in error messages (e.g. the filename).
        """

    def parse_file(self, path: str | Path, encoding: str = "utf-8") -> ProgramNode:
        """Read *path* and parse it."""
        p = Path(path)
        try:
            text = p.read_text(encoding=encoding, errors="replace")
        except OSError as exc:
            raise ParseError(str(exc), source=str(p)) from exc
        return self.parse(text, name=p.name)
