# -*- coding: utf-8 -*-
"""
BibTeX tools for Quarto projects.

This module provides:

- Parsing of BibTeX files into pandas DataFrames using a lightweight parser.
- Extraction of cited keys from .qmd files.
- Construction of a trimmed .bib file containing only the cited entries.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import re

import pandas as pd

from .utils import discover_quarto_sources, extract_front_matter, strip_code_blocks


def parse_bibtex_text(text: str) -> list[dict[str, str]]:
    """
    Parse a BibTeX file into a list of dictionaries.

    Each dict contains:
      - 'type' (entry type, e.g. 'article')
      - 'tag' (the citation key)
      - one key per BibTeX field found

    Assumes all values are of the form:

        field = { ... },

    and that entries are separated by leading '@'.
    """
    rows: list[dict[str, str]] = []

    # Split on '@' and reconstruct minimal entries.
    chunks = re.split('^@', text, flags=re.MULTILINE)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Put back the '@' for the parser; header regex allows optional '@'.
        entry = "@" + chunk
        parsed = _parse_entry_fast(entry)
        if parsed is None:
            parsed = _parse_entry_slow(entry)
        if parsed is not None:
            rows.append(parsed)
        else:
            pass
            # look at this once in a while... 
            # print(f'PARSE FAILED FOR: {entry}')
    return rows


def _parse_entry_fast(entry: str) -> dict[str, str] | None:
    """
    Fast-path parser for well-behaved entries.

    Uses a single regex to capture fields of the form:

        key = {value},

    where 'value' may span multiple lines.
    """
    result: dict[str, str] = {}

    # Normalize Windows copy-paste line breaks that sometimes include spaces.
    entry = entry.replace("\r\n  ", "\n")

    # Step 1: extract type and tag; allow optional leading '@'.
    header_match = re.match(r"@?(\w+)\{([^,]+),", entry)
    if not header_match:
        return None

    et, tag = header_match.groups()
    result["type"], result["tag"] = et, tag.strip()

    # Step 2: remove header and final trailing '}' if present.
    body = entry[header_match.end() :].strip()
    if body.endswith("}"):
        body = body[:-1].strip() + ",\n"

    # Step 3: find all "key = {value},\n" patterns with DOTALL enabled.
    # allow leading spaces
    for match in re.finditer(r" *([a-zA-Z\-]+) *= *{(.*?)},?\n", body, flags=re.DOTALL):
        try:
            key, value = match.groups()
        except ValueError:
            return None
        result[key] = value

    return result


def _parse_entry_slow(entry: str) -> dict[str, str] | None:
    """
    Slow-path parser for entries that defeat the fast regex.

    This parser:
      - finds all occurrences of 'key = {' (with flexible spacing),
      - slices between successive keys,
      - trims trailing ','
      - strips one trailing '}' if present.
    """
    result: dict[str, str] = {}

    header_match = re.match(r"@?(\w+)\{([^,]+),", entry)
    if not header_match:
        return None

    result["type"], result["tag"] = header_match.groups()

    body = entry[header_match.end() :].strip()
    if body.endswith("}"):
        body = body[:-1].strip()

    # Find 'key = {' allowing arbitrary spaces around '='.
    matches = list(re.finditer(r"([a-zA-Z\-]+)\s*=\s*\{", body))
    n = len(matches)

    for i, match in enumerate(matches):
        key = match.group(1)
        val_start = match.end()
        val_end = matches[i + 1].start() if i + 1 < n else len(body)

        value = body[val_start:val_end].rstrip().rstrip(",")

        if value.endswith("}"):
            value = value[:-1].rstrip()

        result[key] = value

    return result


@dataclass
class QuartoBibTex:
    """
    Build trimmed BibTeX files for a Quarto project.

    This class:
      - discovers .qmd sources in the same way as QuartoToc,
      - collects cited keys from '@citekey' style references,
      - discovers BibTeX files from project and per-file YAML,
      - parses the BibTeX into a DataFrame,
      - filters to cited keys only,
      - drops noisy fields and cleans URLs,
      - writes a compact .bib file on request.
    """

    base_dir: Path
    project_yaml: Path | None = None
    file_patterns: tuple[str, ...] = ()
    explicit_files: tuple[Path, ...] = ()
    encoding: str = "utf-8"
    ignore_key_prefixes: str = "sec|fig|tbl|eq|ch|def|thm|exr|exm|lem|prp|REF"
    ignore_key_suffixes: str = r":\.\:\-_"

    trusted_url_patterns: tuple[str, ...] = (
        "acm.org",
        "ams.org",
        "aria.org",
        "arxiv.org",
        "cambridge.org",
        "casact.org",
        "doi.org",
        "elsevier.com",
        "ieee.org",
        "ifrs.org",
        "jstor.org",
        "mdpi.com",
        "nature.com",
        "nber.org",
        "oup.com",
        "projecteuclid.org",
        "sciencedirect.com",
        "siam.org",
        "soa.org",
        "springer.com",
        "springerlink.com",
        "ssrn",
        "tandfonline.com",
        "variancejournal.org",
        "wiley.com",
    )

    _df: pd.DataFrame | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """
        Compile a regex that matches cross-ref style keys like
        sec-1, fig:foo, exr.3, etc., based on ignore_prefixes.
        """
        pattern = (r"^(?:" +
                    self.ignore_key_prefixes +
                    r")[" +
                    self.ignore_key_suffixes +
                    "]"
                    )
        self.ignore_prefix_re = re.compile(pattern)

    @property
    def df(self):
        if self._df is None:
            self.make_df()
        return self._df

    def _discover_sources(self) -> list[Path]:
        """
        Discover the .qmd source files using the same logic as QuartoToc.
        """
        sources, _project_title = discover_quarto_sources(
            base_dir=self.base_dir,
            encoding=self.encoding,
            project_yaml=self.project_yaml,
            file_patterns=self.file_patterns,
            explicit_files=self.explicit_files,
        )
        return sources

    def _project_yaml_path(self) -> Path | None:
        """
        Return the project YAML path, if available.

        Uses self.project_yaml if provided, else tries _quarto.yml / _quarto.yaml.
        """
        if self.project_yaml is not None:
            return self.project_yaml

        yaml_yml = self.base_dir / "_quarto.yml"
        yaml_yaml = self.base_dir / "_quarto.yaml"
        if yaml_yml.exists():
            return yaml_yml
        if yaml_yaml.exists():
            return yaml_yaml
        return None

    def _bib_paths_from_project_yaml(self) -> list[Path]:
        """
        Extract bibliography paths from the project-level YAML, if any.

        Handles only simple patterns:

          bibliography: refs.bib
          bibliography: [a.bib, b.bib]

        and multi-line lists:

          bibliography:
            - a.bib
            - b.bib
        """
        yaml_path = self._project_yaml_path()
        if yaml_path is None:
            return []

        text = yaml_path.read_text(encoding=self.encoding)
        lines = text.splitlines()

        bibs: list[str] = []
        i = 0
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if not s.startswith("bibliography:"):
                i += 1
                continue

            val = s[len("bibliography:") :].strip()

            # Inline list: bibliography: [a.bib, b.bib]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                for piece in inner.split(","):
                    entry = piece.strip().strip("\"'").strip()
                    if entry:
                        bibs.append(entry)
                i += 1
                continue

            # Single value: bibliography: refs.bib
            if val:
                entry = val.strip().strip("\"'").strip()
                if entry:
                    bibs.append(entry)
                i += 1
                continue

            # Multi-line list:
            # bibliography:
            #   - a.bib
            #   - b.bib
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    break
                stripped = nxt.lstrip()
                if not stripped.startswith("- "):
                    break
                entry = stripped[2:].strip().strip("\"'").strip()
                if entry:
                    bibs.append(entry)
                j += 1
            i = j

        paths: list[Path] = []
        for entry in bibs:
            # Project-level bibliography paths are relative to base_dir.
            paths.append(self.base_dir / entry)

        print(f'Found {len(paths)} bibtex files:\n\t', sep='', end='')
        print('\n\t'.join(p.name for p in paths))

        return paths

    def _bib_paths_from_sources(self, sources: Iterable[Path]) -> list[Path]:
        """
        Collect bibliography paths from the YAML front matter of each source.

        The 'bibliography' field in front matter is interpreted as a list
        of paths, relative to the source file's directory.
        """
        paths: set[Path] = set()

        for src in sources:
            text = src.read_text(encoding=self.encoding)
            _title, body_lines, meta = extract_front_matter(text)
            bib_list = meta.get("bibliography")
            if not bib_list:
                continue

            for rel in bib_list:
                rel_path = rel.strip()
                if not rel_path:
                    continue
                paths.add(src.parent / rel_path)

        return sorted(paths)

    def _collect_bib_paths(self, sources: list[Path]) -> list[Path]:
        """
        Collect all BibTeX paths from project YAML and per-file front matter.
        """
        paths: set[Path] = set()

        for p in self._bib_paths_from_project_yaml():
            paths.add(p)

        for p in self._bib_paths_from_sources(sources):
            paths.add(p)

        # Only keep existing files to avoid surprises.
        existing = [p for p in paths if p.exists()]

        return sorted(existing)

    def collect_citations(self, sources: list[Path] | None = None) -> set[str]:
        """
        Scan project sources and return the set of cited BibTeX keys.

        This looks for '@key' patterns outside code blocks and filters out
        keys whose prefixes match ignore_key_prefixes.
        """
        if sources is None:
            sources = self._discover_sources()

        keys: set[str] = set()

        # Regex to find '@key' patterns, avoiding '@@' escapes.
        cite_rex = re.compile(r"(?<!@)@([A-Za-z0-9_:+/-]+)")

        for src in sources:
            text = src.read_text(encoding=self.encoding)
            _title, body_lines, _meta = extract_front_matter(text)
            clean_lines = strip_code_blocks(body_lines)

            for line in clean_lines:
                for key in cite_rex.findall(line):
                    # Ignore cross-refs like sec-..., fig:..., exr., etc.
                    if self.ignore_prefix_re.match(key):
                        continue
                    keys.add(key)

        return keys

    def make_df(self) -> pd.DataFrame:
        """
        Build and return the filtered BibTeX DataFrame for cited keys only.

        The resulting DataFrame has at least the columns:
          - 'type'
          - 'tag'
        plus a subset of common BibTeX fields, with noisy fields removed.
        """
        # qmd source files
        sources = self._discover_sources()
        # citation keys within those sources
        citation_keys = self.collect_citations(sources)
        # paths of bibtex files found referenced
        bib_paths = self._collect_bib_paths(sources)

        rows: list[dict[str, str]] = []
        for path in bib_paths:
            text = path.read_text(encoding=self.encoding)
            rows.extend(parse_bibtex_text(text))

        if not rows:
            self.df = pd.DataFrame()
            return self.df

        df = pd.DataFrame(rows)

        # ------------------------------------------------------
        # for debugging - the full monty
        # df.to_csv('\\tmp\\bib\\FULL-DEBUG.csv', encoding='cp1252', errors='ignore')
        # print(f'DEBUG written with {len(df)} entries.')
        # print(f'{len(sources) = }')
        # print(f'{len(citation_keys) = }')
        # print(f'{len(bib_paths) = }')
        # ------------------------------------------------------

        # Filter to cited keys only.
        if "tag" in df.columns and citation_keys:
            df = df[df["tag"].isin(citation_keys)].copy()

        # ------------------------------------------------------
        # more debugging
        # print(f'AFTER filtering: {len(df)} entries.')
        # matches = set(df.tag)
        # keys = set(citation_keys)
        # unm = keys - matches
        # print(f'{len(unm)} unmatched\n\t', end='', sep='')
        # print('\n\t'.join(sorted(unm)))
        # df.to_csv('\\tmp\\bib\\EXTRACTED-DEBUG.csv', encoding='cp1252', errors='ignore')
        # ------------------------------------------------------

        if df.empty:
            self.df = df
            return df

        # Drop noisy fields by keeping a curated set of columns.
        keep_fields = {
            "type",
            "tag",
            "author",
            "title",
            "year",
            "journal",
            "booktitle",
            "publisher",
            "volume",
            "number",
            "pages",
            "address",
            "doi",
            "url",
            "note",
            "file"
        }

        cols: list[str] = [c for c in df.columns if c in keep_fields]

        # Ensure 'type' and 'tag' are present and first.
        ordered_cols: list[str] = []
        for base in ("type", "tag"):
            if base in cols:
                ordered_cols.append(base)
        for c in cols:
            if c not in ordered_cols:
                ordered_cols.append(c)

        df = df[ordered_cols]

        # Clean URLs based on trusted patterns.
        if "url" in df.columns:
            df["url"] = df["url"].apply(self._filter_url)

        self._df = df
        return df

    def _filter_url(self, url: str | float) -> str | None:
        """
        Return the URL if it matches a trusted pattern, else None.

        The DataFrame will store missing URLs as NaN if pandas is allowed
        to convert None to its missing value representation.
        """
        if not isinstance(url, str):
            return None

        s = url.strip()
        if not s:
            return None

        for pattern in self.trusted_url_patterns:
            if pattern in s:
                return s

        return None

    def write_df(self, output_path: Path | str, encoding: str = '') -> None:
        """
        Write the df to a csv.

        Use encoding = 'cp1252'
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if encoding == '':
            encoding = self.encoding
        self.df.set_index('tag').sort_index().to_csv(output_path, encoding=encoding)

    def write_bib(self, output_path: Path) -> None:
        """
        Write a compact .bib file containing only the cited entries.

        The entries are written in a stable order:
          - sorted by 'tag',
          - fields in a fixed order where possible.
        """
        # nice to have file but don't want in the output
        df = self.df.drop(columns="file")

        if df.empty:
            output_path.write_text("", encoding=self.encoding)
            return

        # Sort by tag to keep output stable.
        df = df.sort_values("author")

        # Define preferred field order after type/tag.
        preferred_order = [
            "author",
            "title",
            "year",
            "journal",
            "booktitle",
            "publisher",
            "address",
            "volume",
            "number",
            "pages",
            "doi",
            "url",
            "note",
        ]

        lines: list[str] = []

        for _idx, row in df.iterrows():
            entry_type = row.get("type", "misc")
            tag = row.get("tag", "").strip()
            if not tag:
                print(f'Missing tag for {row}')
                continue

            # Decide field order for this entry.
            field_names = [c for c in df.columns if c not in {"type", "tag"}]

            ordered_fields: list[str] = []
            for name in preferred_order:
                if name in field_names:
                    ordered_fields.append(name)
            for name in field_names:
                if name not in ordered_fields:
                    ordered_fields.append(name)

            # Build entry.
            lines.append(f"@{entry_type}{{{tag},")
            for name in ordered_fields:
                value = row.get(name)
                if isinstance(value, float) and pd.isna(value):
                    continue
                if value is None:
                    continue
                value_str = str(value).strip()
                if not value_str:
                    continue
                # Wrap the raw value in braces; assume it is already BibTeX-safe.
                lines.append(f"  {name} = {{{value_str}}},")
            lines.append("}")
            lines.append("")  # blank line between entries

        output = "\n".join(lines)
        output_path.write_text(output, encoding=self.encoding)

    def write_links(self, dir_path: Path) -> int:
        """Write links to all files."""
        links_created = 0
        for n, row in self.df.fillna('').iterrows():
            try:
                files = row['file'].split(";")
            except AttributeError:
                print(f'ATTR error for {row["tag"]}, file = {row["file"]}')
            else:
                len_files = len(files)
                if files:
                    for n, f in enumerate(files):
                        f = f.replace(':pdf', '').replace(':C', 'C')
                        p = Path(f)
                        if p.exists():
                            nn = row['tag'] if len_files == 1 else f'{n}-{row["tag"]}'
                            newf = dir_path / f'{nn}.pdf'
                            print(f'{newf} link to {p}')
                            links_created += 1
                        else:
                            print(f'Link  for {row["tag"]} missing: {p}')
        return links_created
