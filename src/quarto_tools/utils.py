"""
Shared utilities for quarto_tools.

This module provides functions for:

- Discovering Quarto project sources (qmd files) in the correct order.
- Extracting YAML front matter and body from .qmd files.
- Stripping code blocks and comments from lines for text-only processing.
"""
from pathlib import Path
from typing import Any, Iterable, Tuple

import re


# Common Quarto cross-reference prefixes and suffixes, used by both
# BibTeX and cross-reference tools.
QUARTO_XREF_PREFIXES = "sec|fig|tbl|eq|ch|def|thm|exr|exm|lem|prp|nte|sol|REF"
QUARTO_XREF_SUFFIXES = r":\.\:\-_"


def discover_quarto_sources(
    base_dir: Path,
    encoding: str = "utf-8",
    project_yaml: Path | None = None,
    file_patterns: Tuple[str, ...] = (),
    explicit_files: Tuple[Path, ...] = (),
) -> tuple[list[Path], str | None]:
    """
    Discover Quarto source files for a project.

    Precedence:
      1) explicit_files (if non-empty),
      2) file_patterns (globs under base_dir),
      3) project_yaml or auto-detected _quarto.(yml|yaml) with chapters/includes.

    Returns a pair (sources, project_title) where:
      - sources is a list of .qmd files in document order,
      - project_title is the project title if found in _quarto.(yml|yaml), else None.
    """
    # 1) explicit files take absolute precedence
    if explicit_files:
        sources = [Path(p) for p in explicit_files]
        return sources, None

    # 2) glob patterns under base_dir
    if file_patterns:
        sources: list[Path] = []
        for pattern in file_patterns:
            # preserve order per-pattern; glob returns in arbitrary order,
            # so sort to keep behavior stable
            matches = sorted(base_dir.glob(pattern))
            sources.extend(matches)

        if not sources:
            patterns_str = ", ".join(repr(p) for p in file_patterns)
            msg = f"No files matched patterns ({patterns_str}) under {base_dir}"
            raise ValueError(msg)

        return sources, None

    # 3) project mode via _quarto.(yml|yaml)
    if project_yaml is not None:
        yaml_path = project_yaml
    else:
        # auto-detect _quarto.yml / _quarto.yaml under base_dir
        yaml_yml = base_dir / "_quarto.yml"
        yaml_yaml = base_dir / "_quarto.yaml"
        if yaml_yml.exists():
            yaml_path = yaml_yml
        elif yaml_yaml.exists():
            yaml_path = yaml_yaml
        else:
            msg = (
                "Cannot find _quarto.yml or _quarto.yaml and no explicit files or "
                "patterns provided."
            )
            raise ValueError(msg)

    yaml_text = yaml_path.read_text(encoding=encoding)
    yaml_split = yaml_text.split("\n")

    project_title: str | None = None

    # extract project title, if present (simple one-line 'title:' only)
    for line in yaml_split:
        s = line.strip()
        if s.startswith("title:"):
            val = s[6:].strip(": ").strip()
            if val and val[0] in "\"'":
                val = val[1:]
            if val and val[-1] in "\"'":
                val = val[:-1]
            project_title = val or None
            break

    # chapters + includes, preserving order, using a simple YAML-like scan
    try:
        start = yaml_split.index("  chapters:") + 1
    except ValueError as exc:
        msg = "Cannot find '  chapters:' block in project YAML."
        raise ValueError(msg) from exc

    sources: list[Path] = []

    for line in yaml_split[start:]:
        # Expect lines like "    - 010-intro.qmd"
        if line.startswith("    - "):
            fn = line[6:].strip()
            if not fn:
                continue
            part_file_path = base_dir / fn
            sources.append(part_file_path)

            # Collect any {{< include ... >}} directives inside the part file
            text = part_file_path.read_text(encoding=encoding)
            includes = [ln for ln in text.split("\n") if ln.startswith("{{< include ")]
            for inc_line in includes:
                # Example form: {{< include 020-files/finance.qmd >}}
                inc = inc_line[12:-4].strip()
                if not inc:
                    continue
                include_path = part_file_path.parent / inc
                sources.append(include_path)
        else:
            # Stop when we leave the "    - " block
            break

    if not sources:
        msg = "No chapter files discovered from project YAML."
        raise ValueError(msg)

    return sources, project_title


def extract_front_matter(
    text: str,
) -> tuple[str | None, list[str], dict[str, Any]]:
    """
    Extract YAML front matter and return (doc_title, body_lines, meta_dict).

    If the file does not start with '---' on the first line, there is no
    front matter, doc_title is None, body_lines is the full file, and
    meta_dict is empty.

    The parser is intentionally minimal and only understands a small subset
    of YAML:
      - 'title: ...' as a single-line string.
      - 'bibliography: something.bib'
      - 'bibliography: [a.bib, b.bib]'
      - multi-line lists:

          bibliography:
            - a.bib
            - b.bib
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines, {}

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        # Unterminated front matter; treat whole file as body
        return None, lines, {}

    front = lines[1:end_idx]
    body = lines[end_idx + 1 :]

    doc_title: str | None = None
    bib_paths: list[str] = []

    i = 0
    while i < len(front):
        raw = front[i]
        s = raw.strip()

        # title: ...
        if s.startswith("title:"):
            val = s[6:].strip(": ").strip()
            if val and val[0] in "\"'":
                val = val[1:]
            if val and val[-1] in "\"'":
                val = val[:-1]
            doc_title = val or doc_title
            i += 1
            continue

        # bibliography: ...
        if s.startswith("bibliography:"):
            val = s[len("bibliography:") :].strip()

            # Inline list: bibliography: [a.bib, b.bib]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                for piece in inner.split(","):
                    entry = piece.strip().strip("\"'").strip()
                    if entry:
                        bib_paths.append(entry)
                i += 1
                continue

            # Single value on same line: bibliography: refs.bib
            if val:
                entry = val.strip().strip("\"'").strip()
                if entry:
                    bib_paths.append(entry)
                i += 1
                continue

            # Multi-line list:
            # bibliography:
            #   - a.bib
            #   - b.bib
            j = i + 1
            while j < len(front):
                nxt = front[j]
                # Stop on a non-indented or blank line
                if not nxt.strip():
                    break
                stripped = nxt.lstrip()
                if not stripped.startswith("- "):
                    break
                entry = stripped[2:].strip().strip("\"'").strip()
                if entry:
                    bib_paths.append(entry)
                j += 1
            i = j
            continue

        i += 1

    meta: dict[str, Any] = {}
    if doc_title is not None:
        meta["title"] = doc_title
    if bib_paths:
        # Always normalize to a list of paths; caller can flatten if desired.
        meta["bibliography"] = bib_paths

    return doc_title, body, meta


def strip_code_blocks(lines: Iterable[str]) -> list[str]:
    """
    Remove fenced code blocks and HTML comments from an iterable of lines.

    This mirrors the behavior used in the original QuartoToc parser:

      - Lines starting or ending fenced code blocks (```).
      - HTML comments <!-- ... --> treated as code/comment regions.

    The parser toggles an 'incode' flag whenever it encounters a code/comment
    marker and drops lines while incode is True.
    """
    incode_rex = re.compile(r"^```|<!\-\-|\-\->|<!\-\-.*?\-\->")
    incode = False
    out: list[str] = []

    for line in lines:
        # Toggle in/out of code or HTML comment blocks based on markers
        for _ in incode_rex.findall(line):
            incode = not incode

        if incode:
            continue

        out.append(line)

    return out


def git_info(base_dir: Path | str) -> tuple[str, str]:
    """
    Return (commit_short, state) for the repo at base_dir.
    commit_short is like 'a1b2c3d'; state is 'clean' or 'dirty'.
    Falls back to ('no-git', 'n/a') if not a git repo or git unavailable.
    """
    from subprocess import run
    try:
        head = run(
            ["git", "-C", str(base_dir), "rev-parse", "--short=7", "HEAD"],
            check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = run(
            ["git", "-C", str(base_dir), "status", "--porcelain"],
            check=True, capture_output=True, text=True
        ).stdout.strip()
        return (head or "no-git", "clean" if dirty == "" else "dirty")
    except Exception:
        return ("no-git", "n/a")
