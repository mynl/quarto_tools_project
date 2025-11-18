"""
quarto_tools command line interface.
"""

from pathlib import Path
import subprocess
import os
import shlex
import subprocess

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, NestedCompleter, PathCompleter
from prompt_toolkit.formatted_text import HTML
import pandas as pd
from greater_tables import GT

from .utils import resolve_quarto_context
from .toc import QuartoToc
from .bibtex import QuartoBibTex, parse_bibtex_text
from .xref import QuartoXRefs
from .tidy import QuartoTidy
from .pytest_qmd import QuartoPyTest
from .consolidate import QuartoConsolidate


# helpers ===================================================================
# this should be in utils?
def qd(df, **kwargs):
    """click enabled suitable quick display method."""
    kwargs = {'show_index': False} | kwargs
    click.echo(GT(df, **kwargs))


def _run_qt_line(ctx: click.Context, line: str, debug: bool = False, prog_name: str = "qt uber") -> None:
    """
    Parse a single qt command line and dispatch it through the main click group.

    Empty lines and comment-only lines (starting with '#') are ignored.
    Any click.SystemExit exceptions are caught so one bad command does not
    terminate an uber or script session.
    """
    line = line.strip()
    if not line:
        return
    if line.startswith("#"):
        return

    try:
        args = shlex.split(line)
    except ValueError as exc:
        click.echo(f"Could not parse line: {line!r} ({exc})")
        return

    if not args:
        return

    if debug:
        click.echo(f"Executing: {args}")

    try:
        # entry is your main click group
        entry.main(args=args, prog_name=prog_name, obj=ctx)
    except SystemExit:
        # swallow click's SystemExit so the REPL/script keeps running
        if debug:
            click.echo("Command raised SystemExit (ignored).")



# main entry point ==========================================================
@click.group()
def entry():
    """CLI for quarto_tools."""
    pass


# toc: table of contents ====================================================
@entry.command()
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.argument("output_file", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Explicit .qmd file(s) to include; may be given multiple times.",
)
@click.option(
    "-c", "--max-columns-per-row",
    type=int,
    default=12,
    show_default=True,
    help="Maximum total subcolumns per row before wrapping.",
)
@click.option(
    "-w", "--column-width",
    type=str,
    default="5cm",
    show_default=True,
    help="Width of each chapter columnm.",
)
@click.option(
    "-h", "--section-max-height",
    type=str,
    default="8cm",
    show_default=True,
    help="Max subcolumn height (e.g., 8cm); set to a small value to force more wrapping.",
)
@click.option(
    "-m", "--chapter-min-height",
    type=str,
    default="auto",
    show_default=True,
    help="Min height of chapter box; auto or 2cm etc.",
)
@click.option(
    "-v", "--max-levels",
    type=int,
    default=-1,
    show_default=True,
    help="Number of levels in TOC, -1 for all levels (default).",
)
@click.option(
    "-u", "--up-level/--no-up-level",
    default=False,
    show_default=True,
    help="Apply up-leveling logic.",
)
@click.option(
    "-b", "--balance-mode",
    type=click.Choice(["stable", "ffd"]),
    default="stable",
    show_default=True,
    help="Subcolumn packing strategy.",
)
@click.option(
    "-n", "--chapter-number",
    type=int,
    default=-1,
    help="TOC for chapter number only (promote chapter to book), more detailed toc for individual chapter; default -1 use whole book.",
)
@click.option(
    "-o", "--omit",
    multiple=True,
    help="Titles to ignore (may be given multiple times).",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH when it is a directory, like ripgrep -g, can be given multiple times.",
)
@click.option(
    "-x", "--execute/--no-execute",
    default=False,
    show_default=True,
    help="Execute LaTeX command to build pdf. Default is no execution.",
)
@click.option(
    "--messy/--tidy",
    default=False,
    show_default=True,
    help="Do not tidy up log and aux files after TeX build. Default is not to be messy.",
)
@click.option(
    "-s", "--svg/--no-svg",
    default=False,
    show_default=True,
    help="If execute, then also create svg file from PDF. Default is no svg.",
)
@click.option(
    "-d", "--debug/--no-debug",
    default=False,
    show_default=True,
    help="Emit extra comments and faint node outlines.",
)
def toc(
    input_path: Path,
    output_file: Path,
    explicit_files: tuple[Path, ...],
    max_columns_per_row: int,
    column_width: str,
    section_max_height: str,
    chapter_min_height: str,
    max_levels: int,
    up_level: bool,
    balance_mode: str,
    chapter_number: int,
    omit: tuple[str],
    file_patterns: tuple[str, ...],
    execute: bool,
    messy: bool,
    svg: bool,
    debug: bool,
) -> None:
    """
    Generate a TikZ TOC from INPUT_PATH and write a standalone TEX file to OUTPUT_FILE.

    INPUT_PATH may be:

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    # Decide how to interpret INPUT_PATH
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    toc = QuartoToc(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        max_columns_per_row=max_columns_per_row,
        column_width=column_width,
        section_max_height=section_max_height,
        chapter_min_height=chapter_min_height,
        max_levels=max_levels,
        up_level=up_level,
        balance_mode=balance_mode,
        omit_titles=set(omit) if omit else None,
        debug=debug,
    )

    toc.write_tex(output_file, chapter_number)
    click.echo(f"Wrote {output_file}")

    if execute:
        result = toc.run_lualatex(output_file)
        if result.returncode == 0:
            click.echo('Built TeX file to PDF')
        else:
            click.echo(f"Error: lualatex failed with return code {result.returncode}")
            click.echo("Captured stderr:")
            click.echo(result.stderr)
        if not messy:
            for ext in ('.aux', '.log'):
                f = output_file.with_suffix(ext)
                if f.exists(): f.unlink()
    if execute and svg and (pdf_file := output_file.with_suffix('.pdf')).exists():
        svg_file = output_file.with_suffix('.svg')
        result = subprocess.run(
            ["pdf2svg", str(pdf_file), str(svg_file)],
            check=False,  # does not raise an error
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,   # separate error from stdout
            text=True,
        )
        if result.returncode != 0:
            click.echo(f"Error: pdf2svg failed with return code {result.returncode}")
            click.echo("Captured stderr:")
            click.echo(result.stderr)

# bibtex  ====================================================
# bibtex: citations and references ===========================================
@entry.command()
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
@click.option(
    "-w", "--write-csv",
    is_flag=True,
    help="Write citation and bib-entry CSV files alongside the project root.",
)
@click.option(
    "-o", "--out-prefix",
    type=str,
    default="quarto_bibtex",
    show_default=True,
    help="Filename prefix for CSV outputs (without extension).",
)
@click.option(
    "--fail-on-error",
    is_flag=True,
    default=False,
    help="Exit with non-zero status if mismatches are found.",
)
def bibtex(
    input_path: Path,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
    write_csv: bool,
    out_prefix: str,
    fail_on_error: bool,
) -> None:
    """
    Scan a Quarto project for citations and BibTeX entries and report issues.

    INPUT_PATH may be:

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qb = QuartoBibTex(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    sources = qb._discover_sources()
    citation_keys = qb.collect_citations(sources)
    bib_paths = qb._collect_bib_paths(sources)

    all_rows: list[dict[str, str]] = []
    for bib_path in bib_paths:
        text = bib_path.read_text(encoding=qb.encoding)
        all_rows.extend(parse_bibtex_text(text))

    bib_df = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()

    if not bib_df.empty and "tag" in bib_df.columns:
        all_tags = set(bib_df["tag"])
    else:
        all_tags = set()

    missing_citations = sorted(citation_keys - all_tags)
    unused_entries = sorted(all_tags - citation_keys)

    num_cites = len(citation_keys)
    num_bib = len(bib_df)
    num_missing = len(missing_citations)
    num_unused = len(unused_entries)

    click.echo(f"Citations found  : {num_cites}")
    click.echo(f"Bib entries      : {num_bib}")
    click.echo(f"Missing entries  : {num_missing}")
    click.echo(f"Unused entries   : {num_unused}")

    if write_csv:
        out_prefix_path = base_dir / out_prefix

        cites_csv = out_prefix_path.with_suffix(".cites.csv")
        bib_csv = out_prefix_path.with_suffix(".bib.csv")
        missing_csv = out_prefix_path.with_suffix(".missing.csv")
        unused_csv = out_prefix_path.with_suffix(".unused.csv")

        pd.DataFrame({"key": sorted(citation_keys)}).to_csv(cites_csv, index=False)
        bib_df.to_csv(bib_csv, index=False)
        pd.DataFrame({"tag": missing_citations}).to_csv(missing_csv, index=False)
        pd.DataFrame({"tag": unused_entries}).to_csv(unused_csv, index=False)

        click.echo("Wrote:")
        click.echo(f"  {cites_csv}")
        click.echo(f"  {bib_csv}")
        click.echo(f"  {missing_csv}")
        click.echo(f"  {unused_csv}")

    if fail_on_error and (num_missing or num_unused):
        raise SystemExit(1)


# @entry.command()
# @click.argument(
#     "project_root",
#     type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
# )
# @click.option(
#     "-b", "--bib-out",
#     type=click.Path(dir_okay=False, path_type=Path),
#     required=True,
#     help="Path for trimmed BibTeX file.",
# )
# @click.option(
#     "-d", "--df-out",
#     type=click.Path(dir_okay=False, path_type=Path),
#     required=False,
#     help="Path for df as csv file, written in same directory as bibfile.",
# )
# @click.option(
#     "-w", "--win-encoding",
#     type=str,
#     required=False,
#     default="",
#     help="Use Windows cp1252 encoding for csv file; default utf-8.",
# )
# # @click.option(
# #     "-k", "--make_links",
# #     default=False,
# #     show_default=True,
# #     help="Create links to underlying files."
# # )
# def bibtex(project_root, bib_out, df_out, win_encoding): # , make_links):
#     """
#     Generate a trimmed BibTeX file from the references in a Quarto project.

#     \b
#     - a Quarto project directory (with _quarto.yml / _quarto.yaml),
#     - a single .qmd file,
#     - a _quarto.yml / _quarto.yaml file.
#     """
#     qb = QuartoBibTex(base_dir=project_root)
#     qb.make_df()
#     qb.write_bib(bib_out)
#     click.echo(f"Wrote trimmed BibTeX to {bib_out} with {len(qb.df)} entries.")

#     if df_out:
#         num = qb.write_df(df_out)
#         click.echo(f"Wrote df to {df_out}.")

    # links NYI
    # if make_links is not None:
    #     links_out = bib_out.parent / "links"
    #     links_out.mkdir(exist_ok=True)
    #     num = qb.write_links(links_out)
    #     click.echo(f"Wrote {num} links to {links_out}.")


# xref: cross referencing ====================================================
@entry.command()
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-w", "--write-csv",
    is_flag=True,
    help="Write defs/refs CSV files alongside the project root.",
)
@click.option(
    "-o", "--out-prefix",
    type=str,
    default="quarto_xrefs",
    show_default=True,
    help="Filename prefix for CSV outputs (without extension).",
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
@click.option(
    "--fail-on-error",
    is_flag=True,
    default=False,
    help="Exit with non-zero status if issues are found.",
)
def xrefs(
    input_path: Path,
    write_csv: bool,
    out_prefix: str,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
    fail_on_error: bool,
) -> None:
    """
    Scan a Quarto project for label definitions and references and report issues.

    INPUT_PATH may be:

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    xr = QuartoXRefs(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    defs_df, refs_df = xr.scan()
    results = xr.validate()

    dup_df = results.get("duplicate_labels_df")
    undef_df = results.get("undefined_refs_df")
    unused_df = results.get("unused_defs_df")

    dup = len(dup_df) if dup_df is not None else 0
    undef = len(undef_df) if undef_df is not None else 0
    unused = len(unused_df) if unused_df is not None else 0

    click.echo(f"Duplicate labels : {dup}")
    click.echo(f"Undefined refs   : {undef}")
    click.echo(f"Unused defs      : {unused}")

    if write_csv:
        out_prefix_path = base_dir / out_prefix
        defs_csv = out_prefix_path.with_suffix(".defs.csv")
        refs_csv = out_prefix_path.with_suffix(".refs.csv")
        defs_df.to_csv(defs_csv, index=False)
        refs_df.to_csv(refs_csv, index=False)
        click.echo(f"Wrote {defs_csv} and {refs_csv}")

    if fail_on_error and (dup or undef or unused):
        raise SystemExit(1)


# @entry.command()
# @click.argument(
#     "project_root",
#     type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
# )
# @click.option(
#     "-w", "--write-csv",
#     is_flag=True,
#     help="Write defs/refs CSV files alongside the project root.",
# )
# @click.option(
#     "-o","--out-prefix",
#     type=str,
#     default="quarto_xrefs",
#     show_default=True,
#     help="Filename prefix for CSV outputs (without extension).",
# )
# @click.option(
#     "-f","--fail-on-error",
#     is_flag=True,
#     default=False,
#     help="Exit with non-zero status if issues are found.",
# )
# def xrefs(project_root, write_csv, out_prefix, fail_on_error):
#     """
#     Scan a Quarto project for label definitions and references and report issues.
#     """
#     xr = QuartoXRefs(base_dir=project_root)
#     defs_df, refs_df = xr.scan()
#     results = xr.validate()

#     summary_df = results["summary_df"]

#     # output results
#     ff = lambda x: f'{int(x):d}'
#     # for k, v in results.items():
#     for k in ['summary_df', 'duplicate_labels_df', 'undefined_refs_df']:
#         v = results[k]
#         try:
#             print(k)
#             print('=' * len(k))
#             print()
#             print(GT(v, large_ok=True, formatters={
#                 'def_count': ff,
#                 'ref_count': ff,
#                 'xref': ff,
#                 # actually boolean
#                 "allowed": lambda x: 'Yes' if x else 'No'
#                  },
#                  max_table_inch_width=12,
#                  show_index=False))
#             print()
#         except:
#             print(f'ISSUE with {k}')
#             print(v)

#     if write_csv:

#         # write in calling dir for now
#         project_root = Path('.')

#         defs_path = project_root / f"{out_prefix}_defs.csv"
#         refs_path = project_root / f"{out_prefix}_refs.csv"
#         results["duplicate_labels_df"].to_csv(
#             project_root / f"{out_prefix}_duplicate_labels.csv",
#             index=False,
#         )
#         results["undefined_refs_df"].to_csv(
#             project_root / f"{out_prefix}_undefined_refs.csv",
#             index=False,
#         )
#         results["unused_defs_df"].to_csv(
#             project_root / f"{out_prefix}_unused_defs.csv",
#             index=False,
#         )
#         defs_df.to_csv(defs_path, index=False)
#         refs_df.to_csv(refs_path, index=False)
#         click.echo(f"Wrote defs to {defs_path}")
#         click.echo(f"Wrote refs to {refs_path}")

#     if fail_on_error and not results["ok"]:
#         raise SystemExit(1)


# tidying ====================================================
@entry.group()
def tidy():
    """Tidy and report on Quarto .qmd files."""
    pass


@tidy.command("flatten-file")
@click.argument(
    "input_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "output_file",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option(
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="Recursively expand nested {{< include >}} directives.",
)
@click.option(
    "--keep-include-markers/--no-keep-include-markers",
    default=False,
    show_default=True,
    help="Wrap inlined sections in HTML comments indicating include boundaries.",
)
def tidy_flatten_file(
    input_file: Path,
    output_file: Path,
    recursive: bool,
    keep_include_markers: bool,
) -> None:
    """
    Flatten a single QMD file by expanding {{< include >}} directives.

    INPUT_FILE is the root .qmd file; OUTPUT_FILE is the flattened result.
    """
    qt = QuartoTidy(base_dir=input_file.parent)

    qt.flatten_file(
        main_file=input_file,
        output_path=output_file,
        recursive=recursive,
        keep_include_markers=keep_include_markers,
    )

    click.echo(f"Wrote flattened file to {output_file}")


@tidy.command("format")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help=(
        "Glob pattern(s) for QMD files relative to INPUT_PATH if it is a directory, "
        "like ripgrep -g; may be given multiple times."
    ),
)
@click.option(
    "--in-place/--no-in-place",
    default=False,
    show_default=True,
    help="Modify files in-place or write tidied copies under OUTPUT_DIR.",
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(dir_okay=True, file_okay=False, path_type=Path),
    required=False,
    help="Output directory when not editing in-place.",
)
@click.option(
    "--remove-comments/--keep-comments",
    default=True,
    show_default=True,
    help="Remove HTML <!-- ... --> comments outside code fences.",
)
@click.option(
    "-w", "--wrap-width",
    type=int,
    required=False,
    help="If set, wrap prose paragraphs to this column width.",
)
def tidy_format(
    input_path: Path,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
    in_place: bool,
    output_dir: Path | None,
    remove_comments: bool,
    wrap_width: int | None,
) -> None:
    """
    Normalize formatting for .qmd files under INPUT_PATH.

    INPUT_PATH may be:

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    if not in_place and output_dir is None:
        raise click.UsageError(
            "OUTPUT_DIR must be provided when using --no-in-place."
        )

    # Decide how to interpret INPUT_PATH (mirror the toc command behavior).
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qt = QuartoTidy(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    df = qt.tidy(
        in_place=in_place,
        output_dir=output_dir,
        remove_comments=remove_comments,
        wrap_width=wrap_width,
    )

    total_files = len(df)
    changed = int(df["changed"].sum()) if not df.empty else 0

    click.echo(f"Tidied {total_files} file(s); changed {changed}.")
    if not in_place and output_dir is not None:
        click.echo(f"Wrote tidied files under {output_dir}")


@tidy.command("report")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help=(
        "Glob pattern(s) for QMD files relative to INPUT_PATH if it is a directory, "
        "like ripgrep -g; may be given multiple times."
    ),
)
@click.option(
    "--xrefs/--no-xrefs",
    default=True,
    show_default=True,
    help="Include cross-reference checks.",
)
@click.option(
    "--bibtex/--no-bibtex",
    default=True,
    show_default=True,
    help="Include citation / BibTeX checks.",
)
@click.option(
    "--python/--no-python",
    "python_blocks",
    default=True,
    show_default=True,
    help="Include Python-code-block inventory.",
)
@click.option(
    "-v", "--verbose/--no-verbose",
    default=False,
    show_default=True,
    help="More verbose output.",
)
def tidy_report(
    input_path: Path,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
    xrefs: bool,
    bibtex: bool,
    python_blocks: bool,
    verbose: bool
) -> None:
    """
    Report on labels, citations, and Python blocks for a Quarto project.

    INPUT_PATH may be:

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    # Same INPUT_PATH interpretation as for toc/format.
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )
    # if input_path.is_dir():
    #     base_dir = input_path
    #     project_yaml: Path | None = None
    #     patterns = file_patterns
    # else:
    #     suffix = input_path.suffix.lower()
    #     if suffix == ".qmd":
    #         base_dir = input_path.parent
    #         project_yaml = None
    #         patterns = ()
    #         if not explicit_files:
    #             explicit_files = (input_path,)
    #     else:
    #         base_dir = input_path.parent
    #         project_yaml = input_path
    #         patterns = file_patterns

    qt = QuartoTidy(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    results = qt.report(
        include_xrefs=xrefs,
        include_bibtex=bibtex,
        include_python=python_blocks,
    )

    if xrefs and "xrefs" in results:
        xr = results["xrefs"]
        dup_df = xr.get("duplicate_labels_df")
        undef_df = xr.get("undefined_refs_df")
        unused_df = xr.get("unused_defs_df")

        dup = len(dup_df) if dup_df is not None else 0
        undef = len(undef_df) if undef_df is not None else 0
        unused = len(unused_df) if unused_df is not None else 0

        click.echo("XREFS:")
        click.echo(f"  duplicate labels : {dup}")
        click.echo(f"  undefined refs   : {undef}")
        click.echo(f"  unused defs      : {unused}")

        if verbose:
            if dup:
                click.echo("DUPLICATE DETAILS")
                qd(dup_df)
            if undef:
                click.echo("UNDEFINED  REF DETAILS")
                qd(undef_df)

    if bibtex and "bibtex" in results:
        br = results["bibtex"]
        citation_keys = br.get("citation_keys") or set()
        bib_df = br.get("bib_df")
        missing_df = br.get("missing_citations_df")
        unused_df = br.get("unused_bib_entries_df")
        bib_paths = br.get("bib_paths")

        num_cites = len(citation_keys)
        num_bib = len(bib_df) if bib_df is not None else 0
        num_missing = len(missing_df) if missing_df is not None else 0
        num_unused = len(unused_df) if unused_df is not None else 0

        click.echo("BIBTEX:")
        click.echo(f"  citations found  : {num_cites}")
        click.echo(f"  bib entries      : {num_bib}")
        click.echo(f"  missing entries  : {num_missing}")
        click.echo(f"  unused entries   : {num_unused}")

        if verbose:
            if dup:
                click.echo("BIBTEX FILES")
                click.echo(bib_paths)
                click.echo("MISSING CITATIONS")
                qd(missing_df)

    if python_blocks and "python" in results:
        pr = results["python"]
        blocks_df = pr.get("blocks_df")
        summary_df = pr.get("summary_df")

        num_blocks = len(blocks_df) if blocks_df is not None else 0
        num_files = len(summary_df) if summary_df is not None else 0

        click.echo("PYTHON BLOCKS:")
        click.echo(f"  files with blocks: {num_files}")
        click.echo(f"  total blocks     : {num_blocks}")


# consolidate: single-file book ================================================
@entry.command()
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.argument(
    "output_file",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option(
    "--comment-front-matter/--strip-front-matter",
    default=False,
    show_default=True,
    help="Preserve per-file YAML front matter as commented blocks.",
)
@click.option(
    "--heading-level",
    type=int,
    default=1,
    show_default=True,
    help="Heading level for chapter titles extracted from front matter.",
)
def consolidate(
    input_path: Path,
    output_file: Path,
    comment_front_matter: bool,
    heading_level: int,
) -> None:
    """
    Consolidate a Quarto project into a single .qmd file.

    INPUT_PATH may be:

    \\b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.

    The output is a monolithic .qmd that flattens {{< include >}} directives
    and inserts chapter headings from per-file 'title:' front matter.
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=(),
        file_patterns=(),
    )

    qc = QuartoConsolidate(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )
    qc.consolidate(
        output_path=output_file,
        comment_front_matter=comment_front_matter,
        heading_level=heading_level,
    )
    click.echo(f"Wrote consolidated file to {output_file}")


# pytesting ====================================================
@entry.group()
def qpytest() -> None:
    """
    Python block extraction and testing for Quarto .qmd files.
    """
    pass


@qpytest.command("collect")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
def qpytest_collect(
    input_path: Path,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
) -> None:
    """
    List all Python code blocks found in Quarto .qmd files under INPUT_PATH.
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qpt = QuartoPyTest(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    df = qpt.collect_blocks()

    click.echo(f"Found {len(df)} python block(s).")
    if df.empty:
        return

    by_file = df.groupby("file")["block_index"].count().reset_index()
    click.echo("")
    click.echo("Blocks per file:")
    for _, row in by_file.iterrows():
        click.echo(f"  {row['file']} : {row['block_index']}")

    # qd(df.head(10))

@qpytest.command("extract")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.argument(
    "output_dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
def qpytest_extract(
    input_path: Path,
    output_dir: Path,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
) -> None:
    """
    Extract Python blocks to .py files under OUTPUT_DIR, one per .qmd file.
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qpt = QuartoPyTest(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    df = qpt.extract(output_dir=output_dir)
    total_files = len(df)
    total_blocks = int(df["blocks"].sum()) if not df.empty else 0

    click.echo(f"Extracted {total_blocks} block(s) from {total_files} file(s).")
    click.echo(f"Scripts written under {output_dir}")


@qpytest.command("run")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-m", "--mode",
    type=click.Choice(["syntax", "exec"], case_sensitive=False),
    default="syntax",
    show_default=True,
    help="Test mode: 'syntax' compiles only; 'exec' executes blocks in-process.",
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
def qpytest_run(
    input_path: Path,
    mode: str,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
) -> None:
    """
    Test Python blocks in .qmd files under INPUT_PATH (single process).


    SEE PMIR.syntax_check --> that's how I want the output...
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qpt = QuartoPyTest(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    df = qpt.run(mode=mode)

    total = len(df)
    if total == 0:
        click.echo("No python blocks found.")
        return

    ok = int(df["ok"].sum())
    failed = total - ok

    click.echo(f"Mode: {mode}")
    click.echo(f"Blocks tested : {total}")
    click.echo(f"Blocks failed : {failed}")

    if failed:
        click.echo("")
        click.echo("Failures:")
        failures = df.loc[~df["ok"], ["file", "block_index", "label", "error_type"]]
        for _, row in failures.iterrows():
            label = row["label"] or ""
            click.echo(
                f"  {row['file']} [block {row['block_index']}] "
                f"{label} -> {row['error_type']}"
            )


@qpytest.command("run-parallel")
@click.argument(
    "input_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    required=False,
    help="Directory for extracted scripts; defaults to base_dir/.qpytest.",
)
@click.option(
    "-n", "--n-workers",
    type=int,
    default=4,
    show_default=True,
    help="Number of concurrent workers.",
)
@click.option(
    "-f", "--file",
    "explicit_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    help="Explicit QMD files to include; may be given multiple times.",
)
@click.option(
    "-g", "--pattern",
    "file_patterns",
    multiple=True,
    help="Glob pattern(s) for QMD files relative to INPUT_PATH, like ripgrep -g.",
)
def qpytest_run_parallel(
    input_path: Path,
    output_dir: Path | None,
    n_workers: int,
    explicit_files: tuple[Path, ...],
    file_patterns: tuple[str, ...],
) -> None:
    """
    Execute chapters in parallel as independent scripts (per .qmd file).
    """
    base_dir, project_yaml, patterns, explicit_files = resolve_quarto_context(
        input_path=input_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    qpt = QuartoPyTest(
        base_dir=base_dir,
        project_yaml=project_yaml,
        file_patterns=patterns,
        explicit_files=explicit_files,
        encoding="utf-8",
    )

    df = qpt.run_parallel(output_dir=output_dir, n_workers=n_workers)

    total = len(df)
    if total == 0:
        click.echo("No python blocks found.")
        return

    ok = int(df["ok"].sum())
    failed = total - ok

    chapters = df[["file", "ok"]].groupby("file").agg(all_ok=("ok", "all")).reset_index()
    chapter_failed = int((~chapters["all_ok"]).sum())

    click.echo("Mode: exec-parallel")
    click.echo(f"Blocks tested      : {total}")
    click.echo(f"Blocks with errors : {failed}")
    click.echo(f"Chapters with errors: {chapter_failed}")

    if failed:
        click.echo("")
        click.echo("First few failing blocks:")
        failures = df.loc[~df["ok"], ["file", "block_index", "label"]].head(10)
        for _, row in failures.iterrows():
            label = row["label"] or ""
            click.echo(
                f"  {row['file']} [block {row['block_index']}] {label}"
            )


# uber  ====================================================
@entry.command()
@click.pass_context
@click.option(
    "-p",
    "--prompt-label",
    type=str,
    default="qt uber",
    show_default=True,
    help="Label shown in the uber prompt.",
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Print parsed commands before executing them.",
)
def uber(ctx: click.Context, prompt_label: str, debug: bool) -> None:
    """
    Interactive shell for quarto_tools.

    Loads the library once, then lets you run qt subcommands repeatedly with
    completion and history. Type 'q' or 'exit' to leave.
    """
    # Build command list from registered subcommands plus a few shell helpers.
    qt_commands = sorted(entry.commands.keys())
    special = ["cd", "pwd", "dir", "cls", "q", "x", "e", "ex", "ev", "quit", "exit", "help", "h", "?"]

    dcommands: dict[str, object] = {name: None for name in qt_commands + special}
    # Use a PathCompleter specifically for cd
    dcommands["cd"] = PathCompleter(only_directories=True, expanduser=True)

    completer = FuzzyCompleter(NestedCompleter(dcommands))
    session = PromptSession(completer=completer)

    def _prompt() -> str:
        cwd = os.getcwd()
        # HTML lets us color the label a bit if you like
        return HTML(f"<ansired>{prompt_label} > </ansired>")
        # return HTML(f"<ansigreeen>{cwd}</ansigreeen> <ansired>{prompt_label} > </ansired>")

    while True:
        try:
            q = session.prompt(_prompt()).strip()

            if not q:
                continue

            if q in {"q", "x", "quit", "exit", ".."}:
                break
            if q in {"h", "?", "help"}:
                click.echo("Type a qt sub-command (e.g. 'toc', 'tidy', 'xref') or 'q' to quit.\n"
                    "Use --help to access CLI built-in help.")
                continue
            if q == "cls":
                os.system("cls")
                continue
            if q in {"pwd", "cwd"}:
                click.echo(os.getcwd())
                continue
            if q in {'e', 'ex'}:
                # windows explorer; not Popen is async run
                subprocess.Popen(["explorer", os.getcwd()])
            if q == "ev":
                # everything
                subprocess.Popen(["C:\\Program Files\\Everything\\Everything.exe", "-search", f"path:{os.getcwd()}"])
            if q.startswith("cd "):
                path = q[3:].strip()
                if path:
                    try:
                        os.chdir(path)
                    except FileNotFoundError:
                        click.echo(f"Directory not found: {path}")
                continue
            if q.startswith("dir") or q.startswith("type "):
                # pass dir and its arguments to cmd
                result = subprocess.run(q, shell=True, text=True, capture_output=True)
                if result.stdout:
                    click.echo(result.stdout.rstrip("\n"))
                if result.stderr:
                    click.echo(result.stderr.rstrip("\n"))
                continue

            # Delegate everything else to the main qt entry point
            _run_qt_line(ctx=ctx, line=q, debug=debug, prog_name="qt uber")

        except KeyboardInterrupt:
            # Ctrl+C: just move to a new prompt
            continue
        except EOFError:
            # Ctrl+D: exit the shell
            break


# scripting  ====================================================
@entry.command()
@click.pass_context
@click.argument(
    "script_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Print parsed commands before executing them.",
)
def script(ctx: click.Context, script_file: Path, debug: bool) -> None:
    """
    Run a series of qt commands from SCRIPT_FILE.

    Lines ending with a backslash '\\' are continued on the next line
    (Python-style). Empty lines and lines starting with '#' are ignored.
    """
    text = script_file.read_text(encoding="utf-8")
    lines = text.splitlines()

    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        logical = " ".join(buffer).strip()
        buffer.clear()
        if logical:
            _run_qt_line(ctx=ctx, line=logical, debug=debug, prog_name="qt script")

    for raw in lines:
        line = raw.rstrip()
        if not line:
            # blank line ends any current command
            flush()
            continue

        if line.endswith("\\"):
            # continuation: drop trailing backslash and keep accumulating
            buffer.append(line[:-1].rstrip())
            continue

        buffer.append(line)
        flush()

    # leftover command without trailing newline
    flush()
