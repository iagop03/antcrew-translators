"""polytranslate CLI — translate legacy code and extract coding standards."""
from __future__ import annotations

import glob as _glob
from pathlib import Path
from typing import List, Optional

try:
    import typer
    from rich.console import Console
    from rich.rule import Rule
except ImportError:
    raise ImportError(
        "CLI dependencies not installed.\n"
        "Run: pip install 'polytranslate[cli]'"
    ) from None

app = typer.Typer(
    name="polytranslate",
    help="Translate legacy code and extract COBOL coding standards.",
    no_args_is_help=True,
)
console = Console()

_COBOL_EXTS = {".cbl", ".cob", ".cpy", ".copy"}
_MAX_JAVA_SIZE = 1 * 1024 * 1024  # 1 MB


# ------------------------------------------------------------------
# translate java-to-cobol
# ------------------------------------------------------------------

translate_app = typer.Typer(help="Translation commands.", no_args_is_help=True)
app.add_typer(translate_app, name="translate")


@translate_app.command(name="java-to-cobol")
def translate_java_to_cobol(
    java_file: Path = typer.Argument(..., help="Java source file to translate.", exists=True),
    standards: Optional[Path] = typer.Option(
        None, "--standards", "-s",
        help=".cbl/.cob or .md/.txt standards file to learn naming from.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output directory. Default: ./cobol_output/",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override LLM model name."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print output without writing files."),
    no_normalize: bool = typer.Option(False, "--no-normalize", help="Skip COBOLNormalizer pass."),
    refine_file: Optional[Path] = typer.Option(
        None, "--refine", "-r",
        help="Existing .cbl to refine instead of translating from scratch.",
    ),
    feedback: Optional[str] = typer.Option(
        None, "--feedback", "-f",
        help="Feedback for --refine mode (required with --refine).",
    ),
) -> None:
    """Translate a Java source file to COBOL.

    Examples::

        polytranslate translate java-to-cobol OrderProcessor.java
        polytranslate translate java-to-cobol OrderProcessor.java -s CLAIMS.cbl
        polytranslate translate java-to-cobol OrderProcessor.java --refine out.cbl --feedback "missing date check"
    """
    from polytranslate.translators.java_to_cobol import JavaToCOBOLTranslator

    # Validate input
    size = java_file.stat().st_size
    if size == 0:
        console.print(f"[red]Java file is empty: {java_file}[/red]")
        raise typer.Exit(1)
    if size > _MAX_JAVA_SIZE:
        console.print(f"[red]Java file too large ({size / 1024:.0f} KB > 1 MB): {java_file}[/red]")
        raise typer.Exit(1)

    java_code = java_file.read_text(encoding="utf-8")
    if not java_code.strip():
        console.print(f"[red]Java file contains only whitespace: {java_file}[/red]")
        raise typer.Exit(1)

    # Build translator
    try:
        translator = JavaToCOBOLTranslator.from_env(model=model)
    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except ImportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Load standards
    if standards:
        console.print(f"[bold]Loading standards[/bold] from {standards.name}…")
        try:
            translator.load_standards(str(standards))
            s = translator.standards
            console.print(
                f"  prefixes: {s.var_prefixes}  |  pattern: {s.paragraph_pattern}  |  "
                f"nesting: {s.max_nesting_levels}"
            )
        except Exception as exc:
            console.print(f"[red]Failed to load standards: {exc}[/red]")
            raise typer.Exit(1)

    # Refine or translate
    normalize = not no_normalize

    if refine_file:
        if not feedback:
            console.print("[red]--feedback is required when using --refine[/red]")
            raise typer.Exit(1)
        current_cobol = refine_file.read_text(encoding="utf-8")
        console.print(f"[bold]Refining[/bold] {refine_file.name} with feedback…")
        try:
            cobol_code = translator.refine(java_code, current_cobol, feedback, normalize=normalize)
        except Exception as exc:
            console.print(f"[red]Refinement error: {exc}[/red]")
            raise typer.Exit(1)
    else:
        lines = len(java_code.splitlines())
        if lines > 150:
            console.print(
                f"[yellow]Large file ({lines} lines) — translating in chunks…[/yellow]"
            )
        else:
            console.print(f"[bold]Translating[/bold] {java_file.name} → COBOL…")
        try:
            cobol_code = translator.translate(java_code, normalize=normalize)
        except TimeoutError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        except Exception as exc:
            console.print(f"[red]Translation error: {exc}[/red]")
            raise typer.Exit(1)

    # Validate
    result = translator.validate(cobol_code)
    if result.errors:
        console.print("[red bold]Validation errors:[/red bold]")
        for e in result.errors:
            console.print(f"  [red]✗ {e}[/red]")
    if result.warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  [yellow]⚠ {w}[/yellow]")
    if result.valid and not result.warnings:
        console.print("[green]✓ COBOL structure valid[/green]")

    # Output
    if dry_run:
        console.print(Rule(f"[cyan]{java_file.stem}.cbl[/cyan]"))
        console.print(cobol_code[:4000] + ("…" if len(cobol_code) > 4000 else ""))
        return

    out_dir = output or Path(".") / "cobol_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (java_file.stem + ".cbl")
    out_path.write_text(cobol_code, encoding="utf-8")
    console.print(f"[green]Written:[/green] {out_path}")
    console.print("[yellow]Review the generated code before using in production.[/yellow]")


# ------------------------------------------------------------------
# translate java-to-cobol-batch
# ------------------------------------------------------------------

@translate_app.command(name="java-to-cobol-batch")
def translate_java_to_cobol_batch(
    pattern: str = typer.Argument(
        ..., help="Glob pattern for Java files, e.g. 'src/**/*.java' or '*.java'.",
    ),
    standards: Optional[Path] = typer.Option(
        None, "--standards", "-s",
        help=".cbl/.cob or .md/.txt standards file to learn naming from (loaded once for all files).",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output directory. Default: ./cobol_output/",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override LLM model name."),
    no_normalize: bool = typer.Option(False, "--no-normalize", help="Skip COBOLNormalizer pass."),
    workers: int = typer.Option(3, "--workers", "-w", help="Max parallel translations (default 3)."),
) -> None:
    """Translate multiple Java files to COBOL in parallel.

    Standards are loaded once and reused for all files. Up to --workers files
    are translated concurrently.

    Examples::

        polytranslate translate java-to-cobol-batch "src/**/*.java" -s CLAIMS.cbl -o ./cobol/
        polytranslate translate java-to-cobol-batch "*.java" --workers 5
    """
    import concurrent.futures as _cf

    from polytranslate.translators.java_to_cobol import JavaToCOBOLTranslator

    # Expand glob
    matched = sorted(_glob.glob(pattern, recursive=True))
    java_files: List[Path] = [Path(p) for p in matched if Path(p).suffix.lower() == ".java"]
    if not java_files:
        console.print(f"[red]No .java files matched: {pattern}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Found {len(java_files)} Java files[/bold]")

    # Build translator once (standards loaded once, cached)
    try:
        translator = JavaToCOBOLTranslator.from_env(model=model)
    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if standards:
        console.print(f"[bold]Loading standards[/bold] from {standards.name}…")
        try:
            translator.load_standards(str(standards))
            s = translator.standards
            console.print(
                f"  prefixes: {s.var_prefixes}  |  pattern: {s.paragraph_pattern}  |  "
                f"nesting: {s.max_nesting_levels}"
            )
        except Exception as exc:
            console.print(f"[red]Failed to load standards: {exc}[/red]")
            raise typer.Exit(1)

    out_dir = output or Path(".") / "cobol_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    normalize = not no_normalize

    ok: List[str] = []
    failed: List[str] = []

    def _translate_one(java_file: Path) -> tuple[Path, str]:
        size = java_file.stat().st_size
        if size == 0 or size > _MAX_JAVA_SIZE:
            raise ValueError(f"Skipping {java_file.name}: empty or too large ({size // 1024} KB)")
        java_code = java_file.read_text(encoding="utf-8")
        return java_file, translator.translate(java_code, normalize=normalize)

    with _cf.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_translate_one, f): f for f in java_files}
        for future in _cf.as_completed(future_map):
            src = future_map[future]
            try:
                java_file, cobol_code = future.result()
                out_path = out_dir / (java_file.stem + ".cbl")
                out_path.write_text(cobol_code, encoding="utf-8")
                validation = translator.validate(cobol_code)
                status = "[green]✓[/green]" if validation.valid else "[yellow]⚠[/yellow]"
                console.print(f"  {status} {java_file.name} → {out_path.name}")
                ok.append(java_file.name)
            except Exception as exc:
                console.print(f"  [red]✗ {src.name}: {exc}[/red]")
                failed.append(src.name)

    console.print(f"\n[bold]Done:[/bold] {len(ok)} translated, {len(failed)} failed")
    if failed:
        raise typer.Exit(1)


# ------------------------------------------------------------------
# extract-standards
# ------------------------------------------------------------------

@app.command(name="extract-standards")
def extract_standards(
    source_file: Path = typer.Argument(
        ..., help="COBOL file (.cbl/.cob/.cpy) or standards doc (.md/.txt).", exists=True
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Write extracted standards to this .md file. Default: print to stdout.",
    ),
) -> None:
    """Extract coding standards from a COBOL file or standards doc.

    Outputs a filled COBOL_STANDARDS.md you can share with your team.

    Examples::

        polytranslate extract-standards CLAIMS.cbl
        polytranslate extract-standards CLAIMS.cbl -o COBOL_STANDARDS.md
    """
    from polytranslate.utils.cobol_standards_extractor import COBOLStandardsExtractor

    extractor = COBOLStandardsExtractor()
    suffix = source_file.suffix.lower()

    try:
        if suffix in _COBOL_EXTS:
            standards = extractor.extract_from_file(str(source_file))
        else:
            standards = extractor.extract_from_documentation(str(source_file))
    except Exception as exc:
        console.print(f"[red]Failed to extract standards: {exc}[/red]")
        raise typer.Exit(1)

    md = _render_standards_md(source_file.name, standards)

    if output:
        output.write_text(md, encoding="utf-8")
        console.print(f"[green]Standards written to:[/green] {output}")
    else:
        console.print(md)


def _render_standards_md(source_name: str, standards) -> str:
    ws = standards.var_prefixes.get("working_storage", "WS")
    wc = standards.var_prefixes.get("constants", "WC")
    lk = standards.var_prefixes.get("linkage", "LK")
    fd = standards.var_prefixes.get("file", "FD")
    para_examples = "\n".join(f"- `{p}`" for p in standards.examples.get("paragraphs", [])[:10])

    return f"""# COBOL Coding Standards
*Extracted from: {source_name}*

---

## Variable Naming

### Working Storage Variables
Prefix: `{ws}-`

### Constants
Prefix: `{wc}-`

### Linkage Section
Prefix: `{lk}-`

### File Section
Prefix: `{fd}-`

---

## Naming Rules

- All UPPERCASE
- Words separated by dashes
- Maximum {standards.max_name_length} characters (COBOL limit)
- No abbreviations except standard ones (ID, QTY, AMT, NO, DT)

---

## Paragraph Naming

### Pattern
`{standards.paragraph_pattern}`

### Examples found in source
{para_examples or "- (no paragraphs detected)"}

### Max Nesting: {standards.max_nesting_levels}

---

## Structure Rules

- Data organization: {standards.data_organization}
- Section order: {" > ".join(standards.section_order)}
"""


def main() -> None:
    app()


if __name__ == "__main__":
    main()
