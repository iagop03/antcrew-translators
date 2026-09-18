"""Python code generator — translate a NormalisedProgram to Python source files.

Produces:
- ``{program_id}_model.py``   — dataclasses for each data section
- ``{program_id}_logic.py``   — translated procedure paragraphs as methods
- ``{program_id}_runner.py``  — entry point / runner script
"""
from __future__ import annotations

from translators.core.ast import (
    CallNode,
    IfNode,
    MoveNode,
    PerformNode,
    ProgramNode,
    StatementNode,
)
from translators.core.generator_base import BaseGenerator, GeneratedFile
from translators.languages.cobol.ast_mapper import CobolASTMapper, NormalisedField, NormalisedProgram


_PIC_TYPE_MAP = {
    "text": "str",
    "integer": "int",
    "decimal": "float",
    "binary": "int",
    "date": "str",
    "timestamp": "str",
}


def _py_type(field: NormalisedField) -> str:
    return _PIC_TYPE_MAP.get(field.base_type, "str")


def _py_default(field: NormalisedField) -> str:
    t = _py_type(field)
    if t == "int":
        return "0"
    if t == "float":
        return "0.0"
    return '""'


def _safe_name(name: str) -> str:
    return name.lower().replace("-", "_")


class PythonGenerator(BaseGenerator):
    """Generate Python from a COBOL AST.

    Usage::

        from translators.languages.cobol import CobolParser
        from translators.targets.python import PythonGenerator

        ast = CobolParser().parse_file("ORDPRC.cbl")
        files = PythonGenerator().generate(ast)
        for f in files:
            f.write("./output")
    """

    language = "python"

    def __init__(self) -> None:
        self._mapper = CobolASTMapper()

    def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
        norm = self._mapper.map(ast)
        stem = _safe_name(norm.program_id)
        return [
            GeneratedFile(f"{stem}_model.py", self._gen_model(norm), language="python"),
            GeneratedFile(f"{stem}_logic.py", self._gen_logic(norm), language="python"),
            GeneratedFile(f"{stem}_runner.py", self._gen_runner(norm), language="python"),
        ]

    # ------------------------------------------------------------------
    # Model file: dataclasses for data sections
    # ------------------------------------------------------------------

    def _gen_model(self, norm: NormalisedProgram) -> str:
        lines = [
            f'"""Data model for COBOL program {norm.program_id}."""',
            "from __future__ import annotations",
            "from dataclasses import dataclass, field",
            "",
        ]

        ws_fields = norm.working_storage_fields
        lk_fields = norm.linkage_fields

        if ws_fields:
            lines += [f"@dataclass", f"class WorkingStorage:"]
            for f in ws_fields:
                lines.append(f"    {_safe_name(f.name)}: {_py_type(f)} = {_py_default(f)}")
            lines.append("")

        if lk_fields:
            lines += ["@dataclass", "class LinkageSection:"]
            for f in lk_fields:
                lines.append(f"    {_safe_name(f.name)}: {_py_type(f)} = {_py_default(f)}")
            lines.append("")

        if not ws_fields and not lk_fields:
            lines += ["@dataclass", "class ProgramData:", "    pass", ""]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logic file: paragraphs as methods
    # ------------------------------------------------------------------

    def _gen_logic(self, norm: NormalisedProgram) -> str:
        stem = _safe_name(norm.program_id)
        lines = [
            f'"""Translated logic for COBOL program {norm.program_id}."""',
            "from __future__ import annotations",
            f"from .{stem}_model import *  # noqa: F401, F403",
            "",
            f"class {_class_name(norm.program_id)}:",
            f'    """Translated from COBOL {norm.program_id}.',
            f"",
            f"    Original author : {norm.author or 'unknown'}",
            f"    Date written    : {norm.date_written or 'unknown'}",
            f'    """',
            "",
            "    def __init__(self) -> None:",
            "        self.ws = WorkingStorage()" if norm.working_storage_fields else "        pass",
            "",
        ]

        for para in norm.paragraphs:
            method = _safe_name(para.name)
            lines.append(f"    def {method}(self) -> None:")
            if para.statements:
                for stmt in para.statements[:20]:
                    translated = self._translate_stmt(stmt)
                    lines.append(f"        {translated}")
            else:
                lines.append("        pass")
            lines.append("")

        return "\n".join(lines)

    def _translate_stmt(self, stmt: StatementNode) -> str:
        if isinstance(stmt, MoveNode):
            dst = _safe_name(stmt.destination)
            src = stmt.source
            return f"self.ws.{dst} = {src!r}  # MOVE {stmt.source} TO {stmt.destination}"
        if isinstance(stmt, CallNode):
            return f"# CALL {stmt.target}  — implement integration"
        if isinstance(stmt, PerformNode):
            method = _safe_name(stmt.target)
            return f"self.{method}()  # PERFORM {stmt.target}"
        if isinstance(stmt, IfNode):
            return f"if {stmt.condition!r}:  # COBOL: IF {stmt.condition}"
        return f"# {stmt.verb}: {stmt.raw[:60]}"

    # ------------------------------------------------------------------
    # Runner file: entry point
    # ------------------------------------------------------------------

    def _gen_runner(self, norm: NormalisedProgram) -> str:
        stem = _safe_name(norm.program_id)
        cls = _class_name(norm.program_id)
        entry = _safe_name(norm.entry_point) if norm.entry_point else "main_para"
        return "\n".join([
            f'"""Runner for {norm.program_id}."""',
            "from __future__ import annotations",
            f"from .{stem}_logic import {cls}",
            "",
            "",
            "def main() -> None:",
            f"    program = {cls}()",
            f"    program.{entry}()",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
            "",
        ])


def _class_name(program_id: str) -> str:
    return "".join(p.capitalize() for p in program_id.replace("-", "_").split("_"))
