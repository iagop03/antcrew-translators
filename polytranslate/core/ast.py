"""Intermediate AST for COBOL source programs.

The translator pipeline works in three stages:
1. Parse COBOL → AST (this module defines the node types)
2. Map language-specific COBOL idioms → normalised AST nodes
3. Generate target language from normalised AST

All nodes are immutable dataclasses.  Walk the tree with the visitor pattern
(see :meth:`ASTNode.accept`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ASTNode:
    """Base class for all AST nodes."""

    def accept(self, visitor: "ASTVisitor") -> Any:
        method_name = f"visit_{type(self).__name__}"
        visit = getattr(visitor, method_name, visitor.generic_visit)
        return visit(self)

    def children(self) -> list["ASTNode"]:
        return []


class ASTVisitor:
    def generic_visit(self, node: ASTNode) -> Any:
        for child in node.children():
            child.accept(self)


# ---------------------------------------------------------------------------
# Program-level nodes
# ---------------------------------------------------------------------------

@dataclass
class ProgramNode(ASTNode):
    """Root node — represents an entire COBOL program."""
    program_id: str
    author: str = ""
    date_written: str = ""
    divisions: list["DivisionNode"] = field(default_factory=list)

    def children(self) -> list[ASTNode]:
        return list(self.divisions)


@dataclass
class DivisionNode(ASTNode):
    """One of the four COBOL divisions."""
    name: str  # IDENTIFICATION | ENVIRONMENT | DATA | PROCEDURE
    sections: list["SectionNode"] = field(default_factory=list)
    statements: list["StatementNode"] = field(default_factory=list)

    def children(self) -> list[ASTNode]:
        return [*self.sections, *self.statements]


@dataclass
class SectionNode(ASTNode):
    name: str  # WORKING-STORAGE | FILE | LINKAGE | …
    items: list["DataItemNode"] = field(default_factory=list)
    paragraphs: list["ParagraphNode"] = field(default_factory=list)

    def children(self) -> list[ASTNode]:
        return [*self.items, *self.paragraphs]


# ---------------------------------------------------------------------------
# Data nodes
# ---------------------------------------------------------------------------

@dataclass
class DataItemNode(ASTNode):
    """A single data item (01-level record or 05/10-level field)."""
    level: int
    name: str
    pic: str = ""  # PIC clause, e.g. "9(10)V99" or "X(40)"
    value: str = ""
    redefines: str = ""
    children_items: list["DataItemNode"] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return bool(self.children_items) or not self.pic

    def children(self) -> list[ASTNode]:
        return list(self.children_items)


# ---------------------------------------------------------------------------
# Procedure nodes
# ---------------------------------------------------------------------------

@dataclass
class ParagraphNode(ASTNode):
    """A COBOL paragraph in the PROCEDURE DIVISION."""
    name: str
    statements: list["StatementNode"] = field(default_factory=list)

    def children(self) -> list[ASTNode]:
        return list(self.statements)


@dataclass
class StatementNode(ASTNode):
    """Generic statement — subclasses represent specific verbs."""
    verb: str = ""
    raw: str = ""


@dataclass
class MoveNode(StatementNode):
    source: str = ""
    destination: str = ""

    def __post_init__(self) -> None:
        self.verb = "MOVE"


@dataclass
class CallNode(StatementNode):
    target: str = ""
    using: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.verb = "CALL"


@dataclass
class PerformNode(StatementNode):
    target: str = ""
    varying: str = ""
    until: str = ""

    def __post_init__(self) -> None:
        self.verb = "PERFORM"


@dataclass
class IfNode(StatementNode):
    condition: str = ""
    then_stmts: list[StatementNode] = field(default_factory=list)
    else_stmts: list[StatementNode] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.verb = "IF"

    def children(self) -> list[ASTNode]:
        return [*self.then_stmts, *self.else_stmts]
