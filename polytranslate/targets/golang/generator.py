"""Go code generator — translate a NormalisedProgram to Go source files.

Produces:
- ``{program_id}_data.go``  — struct types for WORKING-STORAGE / LINKAGE fields
- ``{program_id}_logic.go`` — each paragraph as a method on the program struct
- ``{program_id}_main.go``  — main() entry point
"""
from __future__ import annotations

from polytranslate.core.ast import (
    CallNode,
    IfNode,
    MoveNode,
    PerformNode,
    ProgramNode,
    StatementNode,
)
from polytranslate.core.generator_base import BaseGenerator, GeneratedFile
from polytranslate.languages.cobol.ast_mapper import (
    CobolASTMapper,
    NormalisedField,
    NormalisedProgram,
)

_TYPE_MAP: dict[str, str] = {
    "text": "string",
    "integer": "int64",
    "decimal": "float64",
    "binary": "int64",
    "date": "string",
    "timestamp": "string",
}

_ZERO_MAP: dict[str, str] = {
    "string": '""',
    "int64": "0",
    "float64": "0.0",
}


def _gotype(field: NormalisedField) -> str:
    return _TYPE_MAP.get(field.base_type, "string")


def _gozero(field: NormalisedField) -> str:
    return _ZERO_MAP.get(_gotype(field), "nil")


def _exported(name: str) -> str:
    """Convert COBOL-style name to exported Go identifier (PascalCase)."""
    return "".join(p.capitalize() for p in name.replace("-", "_").split("_"))


def _unexported(name: str) -> str:
    """Convert to unexported camelCase."""
    parts = name.replace("-", "_").split("_")
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _struct_name(program_id: str) -> str:
    return _exported(program_id)


def _pkg_name(program_id: str) -> str:
    return program_id.lower().replace("-", "")


class GoGenerator(BaseGenerator):
    """Generate Go from a COBOL AST.

    Usage::

        from polytranslate.languages.cobol import CobolParser
        from polytranslate.targets.golang import GoGenerator

        ast = CobolParser().parse_file("ORDPRC.cbl")
        files = GoGenerator().generate(ast)
        for f in files:
            f.write("./output")
    """

    language = "go"

    def __init__(self, module: str = "github.com/example/legacy") -> None:
        self._mapper = CobolASTMapper()
        self._module = module

    def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
        norm = self._mapper.map(ast)
        stem = norm.program_id.lower().replace("-", "_")
        pkg = _pkg_name(norm.program_id)
        return [
            GeneratedFile(f"{stem}_data.go", self._gen_data(norm, pkg), language="go"),
            GeneratedFile(f"{stem}_logic.go", self._gen_logic(norm, pkg), language="go"),
            GeneratedFile(f"{stem}_main.go", self._gen_main(norm, pkg), language="go"),
        ]

    # ------------------------------------------------------------------
    # Data structs
    # ------------------------------------------------------------------

    def _gen_data(self, norm: NormalisedProgram, pkg: str) -> str:
        lines = [
            f"package {pkg}",
            "",
            "// WorkingStorage holds COBOL WORKING-STORAGE fields.",
        ]

        ws = norm.working_storage_fields
        lk = norm.linkage_fields

        if ws:
            lines += ["type WorkingStorage struct {"]
            for f in ws:
                field_name = _exported(f.name)
                lines.append(f"\t{field_name} {_gotype(f)}  // PIC {f.cobol_pic}")
            lines += ["}", ""]
        else:
            lines += ["type WorkingStorage struct{}", ""]

        if lk:
            lines += ["// LinkageSection holds COBOL LINKAGE SECTION fields."]
            lines += ["type LinkageSection struct {"]
            for f in lk:
                field_name = _exported(f.name)
                lines.append(f"\t{field_name} {_gotype(f)}  // PIC {f.cobol_pic}")
            lines += ["}", ""]

        lines += [
            f"// {_struct_name(norm.program_id)} is the translated COBOL program.",
            f"type {_struct_name(norm.program_id)} struct {{",
            "\tWS WorkingStorage",
        ]
        if lk:
            lines.append("\tLK LinkageSection")
        lines += ["}", ""]

        lines += [
            f"// New{_struct_name(norm.program_id)} creates a zero-valued program instance.",
            f"func New{_struct_name(norm.program_id)}() *{_struct_name(norm.program_id)} {{",
            f"\treturn &{_struct_name(norm.program_id)}{{}}",
            "}",
            "",
        ]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logic (paragraph methods)
    # ------------------------------------------------------------------

    def _gen_logic(self, norm: NormalisedProgram, pkg: str) -> str:
        sname = _struct_name(norm.program_id)
        lines = [
            f"package {pkg}",
            "",
            "// Paragraph methods translated from COBOL PROCEDURE DIVISION.",
            f"// Original program: {norm.program_id}",
            f"// Author: {norm.author or 'unknown'}",
            "",
        ]

        for para in norm.paragraphs:
            method = _exported(para.name)
            lines.append(f"// {method} translates COBOL paragraph {para.name}.")
            lines.append(f"func (p *{sname}) {method}() {{")
            if para.statements:
                for stmt in para.statements[:20]:
                    lines.append(f"\t{self._translate_stmt(stmt)}")
            else:
                lines.append("\t// TODO: implement")
            lines.append("}")
            lines.append("")

        return "\n".join(lines)

    def _translate_stmt(self, stmt: StatementNode) -> str:
        if isinstance(stmt, MoveNode):
            dst = _exported(stmt.destination)
            src = f'"{stmt.source}"' if not stmt.source.replace("_", "").isalpha() else stmt.source
            return f"p.WS.{dst} = {src} // MOVE {stmt.source} TO {stmt.destination}"
        if isinstance(stmt, CallNode):
            return f"// CALL {stmt.target} — implement integration"
        if isinstance(stmt, PerformNode):
            method = _exported(stmt.target)
            return f"p.{method}() // PERFORM {stmt.target}"
        if isinstance(stmt, IfNode):
            return f"// IF {stmt.condition} — translate condition"
        return f"// {stmt.verb}: {stmt.raw[:60]}"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def _gen_main(self, norm: NormalisedProgram, pkg: str) -> str:
        sname = _struct_name(norm.program_id)
        entry = _exported(norm.entry_point) if norm.entry_point else "MainPara"
        return "\n".join([
            f"package {pkg}",
            "",
            "func main() {",
            f"\tprogram := New{sname}()",
            f"\tprogram.{entry}()",
            "}",
            "",
        ])
