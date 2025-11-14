"""
quarto_tools command line interface.
"""

from pathlib import Path

import click

from .toc import QuartoToc
from .bibtex import QuartoBibTex


@click.group()
def entry():
    """CLI for quarto_tools."""
    pass


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
    "-p", "--promote-chapter",
    type=int,
    default=-1,
    help="Promote chapter to book, more detailed toc for individual chapter; default -1 no promotion.",
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
    promote_chapter: int,
    omit: tuple[str],
    file_patterns: tuple[str, ...],
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
    if input_path.is_dir():
        base_dir = input_path
        project_yaml: Path | None = None
        patterns = file_patterns
    else:
        suffix = input_path.suffix.lower()
        if suffix == ".qmd":
            base_dir = input_path.parent
            project_yaml = None
            patterns = ()
            # if no -f/--file given, treat INPUT_PATH as the single explicit file
            if not explicit_files:
                explicit_files = (input_path,)
        else:
            # treat as explicit project YAML (_quarto.yml / _quarto.yaml)
            base_dir = input_path.parent
            project_yaml = input_path
            patterns = file_patterns

    toc = QuartoToc(
        base_dir=base_dir,
        explicit_files=explicit_files,
        file_patterns=patterns,
        up_level=up_level,
        max_columns_per_row=max_columns_per_row,
        column_width=column_width,
        section_max_height=section_max_height,
        chapter_min_height=chapter_min_height,
        max_levels=max_levels,
        balance_mode=balance_mode,
        omit_titles=set(omit) if omit else None,
        debug=debug,
        project_yaml=project_yaml,
    )

    toc.write_tex(output_file, promote_chapter)

    click.echo(f"Wrote {output_file}")



@entry.command()
@click.argument(
    "project_root",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "-b", "--bib-out",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Path for trimmed BibTeX file.",
)
@click.option(
    "-d", "--df-out",
    type=click.Path(dir_okay=False, path_type=Path),
    required=False,
    help="Path for df as csv file, written in same directory as bibfile.",
)
@click.option(
    "-w", "--win-encoding",
    type=str,
    required=False,
    default="",
    help="Use Windows cp1252 encoding for csv file; default utf-8.",
)
# @click.option(
#     "-k", "--make_links",
#     default=False,
#     show_default=True,
#     help="Create links to underlying files."
# )
def bibtex(project_root, bib_out, df_out, win_encoding): # , make_links):
    """
    Generate a trimmed BibTeX file from the references in a Quarto project.

    \b
    - a Quarto project directory (with _quarto.yml / _quarto.yaml),
    - a single .qmd file,
    - a _quarto.yml / _quarto.yaml file.
    """
    qb = QuartoBibTex(base_dir=project_root)
    qb.make_df()
    qb.write_bib(bib_out)
    click.echo(f"Wrote trimmed BibTeX to {bib_out} with {len(qb.df)} entries.")

    if df_out:
        num = qb.write_df(df_out)
        click.echo(f"Wrote df to {df_out}.")

    # links NYI
    # if make_links is not None:
    #     links_out = bib_out.parent / "links"
    #     links_out.mkdir(exist_ok=True)
    #     num = qb.write_links(links_out)
    #     click.echo(f"Wrote {num} links to {links_out}.")

