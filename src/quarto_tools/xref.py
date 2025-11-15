# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import re

import pandas as pd

from .utils import (discover_quarto_sources, extract_front_matter,
                    QUARTO_XREF_PREFIXES,
                    QUARTO_XREF_SUFFIXES,
                    )

# Keys that look like Quarto-style cross references, based on shared prefixes.
CROSS_REF_KEY_RE = re.compile(
        r"^(?:" + QUARTO_XREF_PREFIXES + r")[" + QUARTO_XREF_SUFFIXES + r"]"
        )


def _split_prefix(label: str) -> str:
    """Return the prefix of a label up to the first '-', ':' or '.'.

    If none of these separators appear, return the full label.
    """
    for sep in ("-", ":", "."):
        idx = label.find(sep)
        if idx != -1:
            return label[:idx]
    return label


def _collect_header_context(lines: List[str]) -> List[str]:
    """Map each line index to the nearest preceding ATX header text."""
    ctx: List[str] = ["" for _ in lines]
    current: str = ""
    header_re = re.compile(r"^(?<!#\|)(#{1,}) (.*?)(?:$| (\{.*\})$)")

    for i, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            current = m.group(2).strip()
        ctx[i] = current

    return ctx


def _scan_file(
    path: Path,
    encoding: str = "utf-8",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Scan a single QMD file for label definitions and references.

    Returns two lists of dicts: (defs_rows, refs_rows).
    """

    text = path.read_text(encoding=encoding)
    _title, body_lines, _meta = extract_front_matter(text)
    header_ctx = _collect_header_context(body_lines)

    defs: List[Dict[str, Any]] = []
    refs: List[Dict[str, Any]] = []

    # Patterns:
    #   - inline labels: {#sec-foo}, {... #fig:bar}, etc.
    inline_label_re = re.compile(r"\{[^}]*?#([A-Za-z0-9:._-]+)[^}]*\}")
    #   - chunk labels: #| label: fig-my-figure
    chunk_label_re = re.compile(r"^#\|\s*label:\s*([A-Za-z0-9:._-]+)\s*$")
    #   - references: @sec-foo, @fig:bar, etc.
    #     Allow '.' inside but strip trailing '.' that ends a sentence.
    ref_re = re.compile(r"(?<!@)@([A-Za-z0-9_:+./-]+)\b")

    # Local code-block / HTML-comment toggle, used only for inline labels and refs.
    incode_rex = re.compile(r"^```|<!\-\-|\-\->|<!\-\-.*?\-\->")
    incode = False

    for idx, line in enumerate(body_lines):
        line_no = idx + 1
        context = header_ctx[idx]
        line_stripped = line.rstrip("\r\n")

        # Chunk labels  (these live inside code blocks, so we always check them)
        m_chunk = chunk_label_re.match(line_stripped)
        if m_chunk:
            label = m_chunk.group(1).strip()
            prefix = _split_prefix(label)
            defs.append(
                {
                    "file": path,
                    "line_no": line_no,
                    "label": label,
                    "prefix": prefix,
                    "kind": "chunk",
                    "header": context,
                    "text": line_stripped,
                }
            )

        # Toggle code / HTML comment state based on markers on this line.
        for _ in incode_rex.findall(line_stripped):
            incode = not incode

        # Inside code: skip inline labels and refs, but we already captured chunk labels.
        if incode:
            continue

        # Inline labels (may be on header or normal text)
        for m in inline_label_re.finditer(line_stripped):
            label = m.group(1).strip()
            prefix = _split_prefix(label)
            defs.append(
                {
                    "file": path,
                    "line_no": line_no,
                    "label": label,
                    "prefix": prefix,
                    "kind": "inline",
                    "header": context,
                    "text": line_stripped,
                }
            )

        # References
        for m in ref_re.finditer(line_stripped):
            label = m.group(1).rstrip(".").strip()
            if not label:
                continue
            xref = CROSS_REF_KEY_RE.match(label) is None
            if xref:
                # no match -> these are bibtex references
                continue
            prefix = _split_prefix(label)
            refs.append(
                {
                    "file": path,
                    "line_no": line_no,
                    "label": label,
                    "prefix": prefix,
                    "xref": xref,
                    "header": context,
                    "text": line_stripped,
                }
            )

    return defs, refs


def validate_quarto_labels(
    defs_df: pd.DataFrame,
    refs_df: pd.DataFrame,
    allowed_prefixes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Validate label definitions and references.

    Returns a dictionary with:
      - ok: bool
      - duplicate_labels_df: duplicated label definitions
      - undefined_refs_df: references without a matching definition
      - unused_defs_df: definitions never referenced
      - prefix_stats_df: counts of prefixes and allowed/unknown flag
      - summary_df: high-level summary of counts
    """
    if defs_df.empty and refs_df.empty:
        summary_df = pd.DataFrame(
            [
                {"issue": "definitions", "count": 0},
                {"issue": "references", "count": 0},
            ]
        )
        return {
            "ok": True,
            "duplicate_labels_df": defs_df.head(0),
            "undefined_refs_df": refs_df.head(0),
            "unused_defs_df": defs_df.head(0),
            "prefix_stats_df": pd.DataFrame(
                columns=["prefix", "def_count", "ref_count", "allowed"]
            ),
            "summary_df": summary_df,
        }

    # Normalize label and prefix columns
    defs_df = defs_df.copy()
    refs_df = refs_df.copy()
    if "label" in defs_df.columns:
        defs_df["label"] = defs_df["label"].astype(str).str.strip()
    if "label" in refs_df.columns:
        refs_df["label"] = refs_df["label"].astype(str).str.strip()
    if "prefix" in defs_df.columns:
        defs_df["prefix"] = defs_df["prefix"].astype(str).str.strip()
    if "prefix" in refs_df.columns:
        refs_df["prefix"] = refs_df["prefix"].astype(str).str.strip()

    # Duplicate label definitions
    dup_mask = defs_df.duplicated(subset=["label"], keep=False)
    duplicate_labels_df = defs_df[dup_mask].sort_values(["label", "file", "line_no"])

    # Undefined references
    defined_labels: Set[str] = set(defs_df["label"])
    undefined_refs_df = refs_df[~refs_df["label"].isin(defined_labels)].copy()
    undefined_refs_df.sort_values(["label", "file", "line_no"], inplace=True)

    # Unused definitions
    referenced_labels: Set[str] = set(refs_df["label"])
    unused_defs_df = defs_df[~defs_df["label"].isin(referenced_labels)].copy()
    unused_defs_df.sort_values(["label", "file", "line_no"], inplace=True)

    # Prefix statistics
    def_counts = (
        defs_df.groupby("prefix", dropna=False)["label"].count().rename("def_count")
    )
    ref_counts = (
        refs_df.groupby("prefix", dropna=False)["label"].count().rename("ref_count")
    )
    prefix_stats_df = (
        pd.concat([def_counts, ref_counts], axis=1)
        .fillna(0)
        .reset_index()
        .rename(columns={"index": "prefix"})
    )
    prefix_stats_df["prefix"] = prefix_stats_df["prefix"].astype(str)

    if allowed_prefixes is not None:
        allowed_set = set(allowed_prefixes)
        prefix_stats_df["allowed"] = prefix_stats_df["prefix"].isin(allowed_set)
    else:
        prefix_stats_df["allowed"] = pd.NA

    # Summary
    summary_rows = [
        {"issue": "definitions", "count": int(len(defs_df))},
        {"issue": "references", "count": int(len(refs_df))},
        {"issue": "duplicate_labels", "count": int(len(duplicate_labels_df))},
        {"issue": "undefined_refs", "count": int(len(undefined_refs_df))},
        {"issue": "unused_defs", "count": int(len(unused_defs_df))},
    ]
    if allowed_prefixes is not None:
        bad_prefixes = prefix_stats_df[
            prefix_stats_df["allowed"] == False  # noqa: E712
        ]
        summary_rows.append(
            {"issue": "bad_prefixes", "count": int(len(bad_prefixes))}
        )

    summary_df = pd.DataFrame(summary_rows)

    ok = (
        len(duplicate_labels_df) == 0
        and len(undefined_refs_df) == 0
        and (
            allowed_prefixes is None
            or not any(prefix_stats_df["allowed"] == False)  # noqa: E712
        )
    )

    return {
        "ok": ok,
        "duplicate_labels_df": duplicate_labels_df,
        "undefined_refs_df": undefined_refs_df,
        "unused_defs_df": unused_defs_df,
        "prefix_stats_df": prefix_stats_df,
        "summary_df": summary_df,
    }


@dataclass
class QuartoXRefs:
    """Scan a Quarto project for label definitions and references.

    This class discovers .qmd sources using the same logic as QuartoToc,
    extracts label definitions and references, and provides basic validation.
    """

    base_dir: Path
    project_yaml: Optional[Path] = None
    file_patterns: Tuple[str, ...] = ()
    explicit_files: Tuple[Path, ...] = ()
    encoding: str = "utf-8"
    allowed_prefixes: Optional[Tuple[str, ...]] = tuple(QUARTO_XREF_PREFIXES.split("|"))

    defs_df: Optional[pd.DataFrame] = field(default=None, init=False)
    refs_df: Optional[pd.DataFrame] = field(default=None, init=False)

    def _discover_sources(self) -> List[Path]:
        """Discover .qmd sources using quarto_tools.utils."""
        sources, _project_title = discover_quarto_sources(
            base_dir=self.base_dir,
            encoding=self.encoding,
            project_yaml=self.project_yaml,
            file_patterns=self.file_patterns,
            explicit_files=self.explicit_files,
        )
        return sources

    def scan(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Scan project sources and populate defs_df and refs_df."""
        sources = self._discover_sources()

        all_defs: List[Dict[str, Any]] = []
        all_refs: List[Dict[str, Any]] = []

        for path in sources:
            defs_rows, refs_rows = _scan_file(path, encoding=self.encoding)
            all_defs.extend(defs_rows)
            all_refs.extend(refs_rows)

        self.defs_df = pd.DataFrame(all_defs)
        self.refs_df = pd.DataFrame(all_refs)

        # Make file paths relative to base_dir to keep tables narrow and readable.
        if not self.defs_df.empty and "file" in self.defs_df.columns:
            self.defs_df["file"] = self.defs_df["file"].apply(
                lambda p: p.relative_to(self.base_dir)
                if isinstance(p, Path) and (p == self.base_dir or self.base_dir in p.parents)
                else p
            )
        if not self.refs_df.empty and "file" in self.refs_df.columns:
            self.refs_df["file"] = self.refs_df["file"].apply(
                lambda p: p.relative_to(self.base_dir)
                if isinstance(p, Path) and (p == self.base_dir or self.base_dir in p.parents)
                else p
            )

        return self.defs_df, self.refs_df

    def validate(self) -> Dict[str, Any]:
        """Validate labels and references, returning a summary dictionary."""
        if self.defs_df is None or self.refs_df is None:
            self.scan()

        assert self.defs_df is not None
        assert self.refs_df is not None

        return validate_quarto_labels(
            defs_df=self.defs_df,
            refs_df=self.refs_df,
            allowed_prefixes=self.allowed_prefixes,
        )
