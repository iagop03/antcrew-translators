"""Java code generator — translate a NormalisedProgram to Java source files.

Produces:
- ``{ProgramId}Data.java``   — POJO class for WORKING-STORAGE / LINKAGE fields
- ``{ProgramId}.java``       — main class with each paragraph as a method
- ``{ProgramId}Runner.java`` — entry point with main(String[] args)
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
from polytranslate.languages.cobol.ast_mapper import CobolASTMapper, NormalisedField, NormalisedProgram


_TYPE_MAP: dict[str, str] = {
    "text": "String",
    "integer": "int",
    "decimal": "double",
    "binary": "long",
    "date": "String",
    "timestamp": "String",
}

_DEFAULT_MAP: dict[str, str] = {
    "String": '""',
    "int": "0",
    "double": "0.0",
    "long": "0L",
}


def _jtype(field: NormalisedField) -> str:
    return _TYPE_MAP.get(field.base_type, "String")


def _jdefault(field: NormalisedField) -> str:
    return _DEFAULT_MAP.get(_jtype(field), "null")


def _camel(name: str) -> str:
    parts = name.lower().replace("-", "_").split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _class_name(program_id: str) -> str:
    return "".join(p.capitalize() for p in program_id.replace("-", "_").split("_"))


def _safe_name(name: str) -> str:
    return _camel(name)


class JavaGenerator(BaseGenerator):
    """Generate Java from a COBOL AST.

    Usage::

        from polytranslate.languages.cobol import CobolParser
        from polytranslate.targets.java import JavaGenerator

        ast = CobolParser().parse_file("ORDPRC.cbl")
        files = JavaGenerator().generate(ast)
        for f in files:
            f.write("./output")
    """

    language = "java"

    def __init__(self, package: str = "com.example.legacy") -> None:
        self._mapper = CobolASTMapper()
        self._package = package

    def generate(self, ast: ProgramNode) -> list[GeneratedFile]:
        norm = self._mapper.map(ast)
        cls = _class_name(norm.program_id)
        return [
            GeneratedFile(f"{cls}Data.java", self._gen_data(norm, cls), language="java"),
            GeneratedFile(f"{cls}.java", self._gen_logic(norm, cls), language="java"),
            GeneratedFile(f"{cls}Runner.java", self._gen_runner(norm, cls), language="java"),
        ]

    # ------------------------------------------------------------------
    # Data POJO
    # ------------------------------------------------------------------

    def _gen_data(self, norm: NormalisedProgram, cls: str) -> str:
        lines = [
            f"package {self._package};",
            "",
            "/**",
            f" * Data fields for COBOL program {norm.program_id}.",
            f" * Author: {norm.author or 'unknown'}",
            f" * Date written: {norm.date_written or 'unknown'}",
            " */",
            f"public class {cls}Data {{",
            "",
        ]

        fields = (norm.working_storage_fields + norm.linkage_fields) or []
        for field in fields:
            jt = _jtype(field)
            jd = _jdefault(field)
            fname = _safe_name(field.name)
            lines.append(f"    private {jt} {fname} = {jd};  // COBOL: {field.name} PIC {field.cobol_pic}")

        if fields:
            lines.append("")
            # Getters and setters
            for field in fields:
                jt = _jtype(field)
                fname = _safe_name(field.name)
                getter = "get" + fname[0].upper() + fname[1:]
                setter = "set" + fname[0].upper() + fname[1:]
                lines += [
                    f"    public {jt} {getter}() {{ return {fname}; }}",
                    f"    public void {setter}({jt} {fname}) {{ this.{fname} = {fname}; }}",
                    "",
                ]

        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logic class
    # ------------------------------------------------------------------

    def _gen_logic(self, norm: NormalisedProgram, cls: str) -> str:
        lines = [
            f"package {self._package};",
            "",
            "/**",
            f" * Translated logic for COBOL program {norm.program_id}.",
            f" * Author: {norm.author or 'unknown'}",
            " */",
            f"public class {cls} {{",
            "",
            f"    private final {cls}Data data = new {cls}Data();",
            "",
        ]

        for para in norm.paragraphs:
            method = _safe_name(para.name)
            lines.append(f"    // COBOL paragraph: {para.name}")
            lines.append(f"    public void {method}() {{")
            if para.statements:
                for stmt in para.statements[:20]:
                    lines.append(f"        {self._translate_stmt(stmt)}")
            else:
                lines.append("        // TODO: implement")
            lines.append("    }")
            lines.append("")

        lines.append("}")
        return "\n".join(lines)

    def _translate_stmt(self, stmt: StatementNode) -> str:
        if isinstance(stmt, MoveNode):
            dst = _safe_name(stmt.destination)
            setter = "set" + dst[0].upper() + dst[1:]
            src = stmt.source if stmt.source.isidentifier() else f'"{stmt.source}"'
            return f"data.{setter}({src});  // MOVE {stmt.source} TO {stmt.destination}"
        if isinstance(stmt, CallNode):
            return f"// CALL {stmt.target} — implement integration"
        if isinstance(stmt, PerformNode):
            method = _safe_name(stmt.target)
            return f"{method}();  // PERFORM {stmt.target}"
        if isinstance(stmt, IfNode):
            return f"// IF {stmt.condition} — translate condition"
        return f"// {stmt.verb}: {stmt.raw[:60]}"

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def _gen_runner(self, norm: NormalisedProgram, cls: str) -> str:
        entry = _safe_name(norm.entry_point) if norm.entry_point else "mainPara"
        return "\n".join([
            f"package {self._package};",
            "",
            "/**",
            f" * Entry point for translated COBOL program {norm.program_id}.",
            " */",
            f"public class {cls}Runner {{",
            "",
            "    public static void main(String[] args) {",
            f"        {cls} program = new {cls}();",
            f"        program.{entry}();",
            "    }",
            "",
            "}",
            "",
        ])
