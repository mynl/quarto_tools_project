# -*- coding: utf-8 -*-
"""
quarto_tools.py

Scan a Quarto project tree for label definitions and references in .qmd files.

Inputs:
    dir_in: a Path to the directory to scan (searched recursively).

Outputs:
    Two pandas.DataFrames:
        defs_df:    rows for each label definition (e.g., {#sec-...}, {#fig-...}, "#| label: tbl-...")
        refs_df:    rows for each label reference (e.g., @sec-..., @fig-..., @tbl-..., @eq-...)

Columns (both frames share most columns):
    dirname         directory containing file, relative to dir_in
    filename        file name (e.g., "post.qmd")
    relpath         POSIX-style relative path from dir_in to file
    line_no         1-based line number where the match occurs
    col_start       1-based column index of the match start
    col_end         1-based column index of the match end (inclusive)
    match_text      exact matched text (e.g., "{#sec-intro}" or "@fig-setup")
    label           normalized label (e.g., "sec-intro" or "fig-setup")
    kind            for defs: one of {"attr_id","chunk_label"}; for refs: {"xref"}
    prefix          leading type prefix if present (e.g., "sec","fig","tbl","eq"), else ""
    header_ctx      nearest preceding ATX header text on or above this line (best-effort)
    fence_ignored   False (rows always excluded from fenced code)

Notes:
    - Fenced code blocks (``` … ```) are skipped so code samples do not pollute results.
    - Citations like [@smith2020] are ignored; only cross-ref-style "@label" tokens are collected.
    - Later renaming support can operate by joining on (relpath, line_no, col_start, col_end).

Windows:
    Run as:  python -m quarto_labels --dir-in X:\\path\\to\\project
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

import click
import pandas as pd


# Regex for fenced code blocks start/end (supports language/class fences)
FENCE_RE = re.compile(r"^(```+|~~~+)")
# ATX headers for simple section context extraction
ATX_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# Definitions:
#   1) Pandoc/Quarto attribute identifiers: {#label} anywhere on a line (often after headers, figures, equations)
ATTR_ID_RE = re.compile(r"\{#([A-Za-z0-9:_\-\.]+)\}")
#   2) Quarto/knitr-style chunk metadata comment: '#| label: xxx'
CHUNK_LABEL_RE = re.compile(r"^\s*#\|\s*label\s*:\s*([A-Za-z0-9:_\-\.]+)\s*$")

# References:
#   Cross-refs are '@label' tokens. We:
#    - exclude citations '[@key]' via negative lookbehind for '['
#    - allow prefixes like sec-, fig-, tbl-, eq-, lst-, algo-, thm-, etc., but do not require them
#   Capture group 1 is the label without the leading '@'
XREF_RE = re.compile(r"(?<!\[)@([A-Za-z0-9:_\-\.]+)")

# Typical prefixes to extract (not enforced for validity; used for the 'prefix' column only)
KNOWN_PREFIXES = ("sec", "fig", "tbl", "eq", "lst", "algo", "thm", "lem", "cor", "def", "prp", "exm", "app", "ch")


@dataclass(frozen=True)
class MatchRow:
    dirname: str
    filename: str
    relpath: str
    line_no: int
    col_start: int
    col_end: int
    match_text: str
    label: str
    kind: str
    prefix: str
    header_ctx: str
    fence_ignored: bool = False  # retained for schema stability; always False for yielded rows


def _nearest_prefix(label: str) -> str:
    """
    Extract known prefix from a label if present. E.g., 'fig-setup' -> 'fig'.
    Returns empty string if no known prefix is found.
    """
    if "-" in label:
        maybe = label.split("-", 1)[0]
        if maybe in KNOWN_PREFIXES:
            return maybe
    return ""


def _iter_qmd_files(root: Path) -> Iterator[Path]:
    """
    Yield .qmd files under root recursively.
    """
    yield from root.rglob("*.qmd")


def _collect_header_context(lines: List[str]) -> List[str]:
    """
    Build a list mapping each line index to the nearest preceding ATX header text.
    """
    ctx: List[str] = [""] * len(lines)
    current = ""
    for i, line in enumerate(lines):
        m = ATX_HEADER_RE.match(line)
        if m:
            # Header text without trailing ID braces if present
            hdr = m.group(2).strip()
            # Strip trailing attribute ID for clarity in context
            hdr = ATTR_ID_RE.sub("", hdr).strip()
            current = hdr
        ctx[i] = current
    return ctx


def _scan_file(
    file_path: Path,
    relbase: Path,
) -> Tuple[List[MatchRow], List[MatchRow]]:
    """
    Scan a single .qmd file for definition and reference matches, skipping fenced code blocks.
    """
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header_ctx_by_line = _collect_header_context(lines)

    defs: List[MatchRow] = []
    refs: List[MatchRow] = []

    # Keep simple state for fenced code skipping; supports ``` and ~~~
    in_fence = False
    fence_tick = ""

    relpath = file_path.relative_to(relbase).as_posix()
    dirname = file_path.parent.relative_to(relbase).as_posix() if file_path.parent != relbase else ""
    filename = file_path.name

    for idx, line in enumerate(lines):
        # Fence toggle
        if FENCE_RE.match(line):
            tick = FENCE_RE.match(line).group(1)
            if not in_fence:
                in_fence = True
                fence_tick = tick
            else:
                # Close only if the same fence-type length opens/closes; be permissive on length
                in_fence = False
                fence_tick = ""
            continue

        if in_fence:
            continue  # ignore content inside fences

        # Definitions: attribute IDs anywhere on line
        for m in ATTR_ID_RE.finditer(line):
            label = m.group(1)
            col_start = m.start() + 1  # 1-based column index
            col_end = m.end()
            defs.append(
                MatchRow(
                    dirname=dirname,
                    filename=filename,
                    relpath=relpath,
                    line_no=idx + 1,
                    col_start=col_start,
                    col_end=col_end,
                    match_text=m.group(0),
                    label=label,
                    kind="attr_id",
                    prefix=_nearest_prefix(label),
                    header_ctx=header_ctx_by_line[idx],
                )
            )

        # Definitions: chunk comment labels
        cm = CHUNK_LABEL_RE.match(line)
        if cm:
            label = cm.group(1)
            # Column span: the 'label' token in the line
            lab_span = re.search(re.escape(label), line)
            if lab_span:
                col_start = lab_span.start() + 1
                col_end = lab_span.end()
            else:
                col_start = 1
                col_end = len(line)
            defs.append(
                MatchRow(
                    dirname=dirname,
                    filename=filename,
                    relpath=relpath,
                    line_no=idx + 1,
                    col_start=col_start,
                    col_end=col_end,
                    match_text=label,
                    label=label,
                    kind="chunk_label",
                    prefix=_nearest_prefix(label),
                    header_ctx=header_ctx_by_line[idx],
                )
            )

        # References: cross-refs '@label' but not citations '[@key]'
        for m in XREF_RE.finditer(line):
            label = m.group(1)
            # Heuristic: skip obvious bibliography citations that contain commas or spaces (rare after our pattern)
            if "," in label:
                continue
            col_start = m.start() + 1
            col_end = m.end()
            refs.append(
                MatchRow(
                    dirname=dirname,
                    filename=filename,
                    relpath=relpath,
                    line_no=idx + 1,
                    col_start=col_start,
                    col_end=col_end,
                    match_text=m.group(0),
                    label=label,
                    kind="xref",
                    prefix=_nearest_prefix(label),
                    header_ctx=header_ctx_by_line[idx],
                )
            )

    return defs, refs


def find_labels_and_refs(dir_in: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Walk dir_in for .qmd files and return (defs_df, refs_df).
    """
    dir_in = dir_in.resolve()
    all_defs: List[MatchRow] = []
    all_refs: List[MatchRow] = []

    for qmd in _iter_qmd_files(dir_in):
        fdefs, frefs = _scan_file(qmd, dir_in)
        all_defs.extend(fdefs)
        all_refs.extend(frefs)

    defs_df = pd.DataFrame([r.__dict__ for r in all_defs])
    refs_df = pd.DataFrame([r.__dict__ for r in all_refs])

    # Sort for convenience: by relpath then line_no then col_start
    if not defs_df.empty:
        defs_df = defs_df.sort_values(["relpath", "line_no", "col_start"], kind="mergesort").reset_index(drop=True)
    if not refs_df.empty:
        refs_df = refs_df.sort_values(["relpath", "line_no", "col_start"], kind="mergesort").reset_index(drop=True)

    return defs_df, refs_df


def validate_quarto_labels(
    defs_df: pd.DataFrame,
    refs_df: pd.DataFrame,
    allowed_prefixes: set[str] | None = None,
) -> dict[str, pd.DataFrame | bool]:
    """
    Validate uniqueness of label definitions and the consistency between
    label definitions (defs_df) and references (refs_df).

    Inputs:
        defs_df:
            DataFrame produced by the scanner with at least:
            ['label','relpath','line_no','col_start','kind','prefix']
        refs_df:
            DataFrame produced by the scanner with at least:
            ['label','relpath','line_no','col_start','kind','prefix']
        allowed_prefixes:
            Optional set of allowed label prefixes (e.g., {'sec','fig','tbl','eq'}).
            If provided, labels with other prefixes are flagged.

    Returns:
        A dict with:
            ok: bool  # True iff no duplicates, no undefined refs, no cross-kind/relpath collisions
            dup_defs_df: DataFrame of labels defined more than once (count > 1)
            collisions_df: Same label defined in multiple files (relpath nunique > 1), rows are the defining sites
            cross_kind_df: Same label defined with multiple 'kind' values
            undefined_refs_df: References whose label is not defined
            unused_defs_df: Definitions that are never referenced
            invalid_prefix_defs_df: Definitions with disallowed prefix (only if allowed_prefixes provided)
            invalid_prefix_refs_df: References with disallowed prefix (only if allowed_prefixes provided)
            summary_df: One-row counts of each failure category
    """
    results: dict[str, pd.DataFrame | bool] = {}

    # Normalize inputs (empty frames still work)
    defs = defs_df.copy() if defs_df is not None else pd.DataFrame(columns=["label"])
    refs = refs_df.copy() if refs_df is not None else pd.DataFrame(columns=["label"])

    # Duplicate definitions by label
    defs_count = (
        defs.groupby("label", dropna=False)
        .agg(count=("label", "size"), n_files=("relpath", "nunique"), kinds=("kind", lambda s: sorted(set(s))))
        .reset_index()
    )
    dup_defs_df = defs_count.loc[defs_count["count"] > 1].sort_values(["count", "label"], ascending=[False, True])
    results["dup_defs_df"] = dup_defs_df

    # Collisions: same label defined in multiple files
    multi_file_labels = set(defs_count.loc[defs_count["n_files"] > 1, "label"])
    collisions_df = (
        defs.loc[defs["label"].isin(multi_file_labels)]
        .sort_values(["label", "relpath", "line_no", "col_start"], kind="mergesort")
        .reset_index(drop=True)
    )
    results["collisions_df"] = collisions_df

    # Cross-kind: same label with multiple definition kinds (e.g., 'attr_id' and 'chunk_label')
    multi_kind_labels = set(
        defs_count.loc[defs_count["kinds"].map(len) > 1, "label"]
    )
    cross_kind_df = (
        defs.loc[defs["label"].isin(multi_kind_labels)]
        .sort_values(["label", "kind", "relpath", "line_no", "col_start"], kind="mergesort")
        .reset_index(drop=True)
    )
    results["cross_kind_df"] = cross_kind_df

    # Undefined references: labels referenced but never defined
    defined_labels = set(defs["label"].dropna().astype(str))
    undefined_mask = ~refs["label"].astype(str).isin(defined_labels)
    undefined_refs_df = refs.loc[undefined_mask].sort_values(
        ["label", "relpath", "line_no", "col_start"], kind="mergesort"
    )
    results["undefined_refs_df"] = undefined_refs_df.reset_index(drop=True)

    # Unused definitions: labels defined but never referenced
    referenced_labels = set(refs["label"].dropna().astype(str))
    unused_defs_df = defs.loc[~defs["label"].astype(str).isin(referenced_labels)].sort_values(
        ["label", "relpath", "line_no", "col_start"], kind="mergesort"
    )
    results["unused_defs_df"] = unused_defs_df.reset_index(drop=True)

    # Optional prefix validation
    if allowed_prefixes is not None:
        # Empty/unknown prefixes are flagged (strict)
        invalid_prefix_defs_df = defs.loc[~defs["prefix"].isin(allowed_prefixes)].sort_values(
            ["label", "relpath", "line_no", "col_start"], kind="mergesort"
        )
        invalid_prefix_refs_df = refs.loc[~refs["prefix"].isin(allowed_prefixes)].sort_values(
            ["label", "relpath", "line_no", "col_start"], kind="mergesort"
        )
    else:
        invalid_prefix_defs_df = pd.DataFrame(columns=defs.columns if not defs.empty else [])
        invalid_prefix_refs_df = pd.DataFrame(columns=refs.columns if not refs.empty else [])

    results["invalid_prefix_defs_df"] = invalid_prefix_defs_df.reset_index(drop=True)
    results["invalid_prefix_refs_df"] = invalid_prefix_refs_df.reset_index(drop=True)

    # Summary and overall status
    summary = {
        "n_defs": int(len(defs)),
        "n_refs": int(len(refs)),
        "dup_defs": int(len(dup_defs_df)),
        "collision_rows": int(len(collisions_df)),
        "cross_kind_rows": int(len(cross_kind_df)),
        "undefined_refs": int(len(undefined_refs_df)),
        "unused_defs": int(len(unused_defs_df)),
        "invalid_prefix_defs": int(len(invalid_prefix_defs_df)),
        "invalid_prefix_refs": int(len(invalid_prefix_refs_df)),
    }
    results["summary_df"] = pd.DataFrame([summary])

    ok = (
        summary["dup_defs"] == 0
        and summary["collision_rows"] == 0
        # do not regard cross kind as an error
        # and summary["cross_kind_rows"] == 0
        and summary["undefined_refs"] == 0
    )
    results["ok"] = ok

    return results


@click.command()
@click.option(
    "-d", "--dir-in",
    "dir_in",
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    required=True,
    help="Root directory to scan recursively for .qmd files.",
)
@click.option(
    "-o", "--out-prefix",
    "out_prefix",
    type=str,
    default="qmd_labels",
    show_default=True,
    help="Prefix for optional CSV outputs: {prefix}_defs.csv and {prefix}_refs.csv in dir_in.",
)
@click.option(
    "-w", "--write-csv/--no-write-csv",
    default=False,
    show_default=True,
    help="If set, write CSVs using out-prefix.",
)
def entry(dir_in: Path, out_prefix: str, write_csv: bool) -> None:
    """
    CLI entry point: prints summary counts; optionally writes CSVs to dir_in.
    """
    defs_df, refs_df = find_labels_and_refs(dir_in)

    click.echo(f"Scanned: {dir_in}")
    click.echo(f"Definitions: {len(defs_df)}")
    click.echo(f"References:  {len(refs_df)}")

    if write_csv:
        defs_path = Path(f"{out_prefix}_defs.csv")
        refs_path = Path(f"{out_prefix}_refs.csv")
        defs_df.to_csv(defs_path.as_posix(), index=False, encoding="utf-8")
        refs_df.to_csv(refs_path.as_posix(), index=False, encoding="utf-8")
        click.echo(f"Wrote: {defs_path}")
        click.echo(f"Wrote: {refs_path}")


if __name__ == "__main__":
    entry()
