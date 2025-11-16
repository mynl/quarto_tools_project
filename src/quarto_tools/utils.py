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


def resolve_quarto_context(
    input_path: Path,
    explicit_files: tuple[Path, ...] = (),
    file_patterns: tuple[str, ...] = (),
) -> tuple[Path, Path | None, tuple[str, ...], tuple[Path, ...]]:
    """
    Resolve INPUT_PATH into a canonical Quarto project context.

    This function centralizes all path/YAML discovery rules used by the
    quarto_tools CLI (tidy, toc, xref, bibtex, pytest).  All commands should
    use this function so that project discovery behaves consistently.

    INPUT_PATH may refer to any of the following:

      (A) A directory containing a _quarto.yml or _quarto.yaml file.
          → Treated as a Quarto project root.
          → All project files (chapters, posts, etc.) are discovered using
            the YAML file.  file_patterns and explicit_files may override
            this if provided.

      (B) A directory without a Quarto YAML file.
          → Treated as a generic folder of .qmd files.
          → Discovery falls back to file_patterns (glob-like) or, if none
            are supplied, to the default “all .qmd files under directory”.
          → explicit_files may override this.

      (C) A single .qmd file.
          → Treated as a one-file “project”.
          → base_dir is set to the file’s parent.
          → project_yaml is None.
          → Unless explicit_files is already given, the .qmd file becomes
            the only explicit source file and patterns are ignored.

      (D) A standalone _quarto.yml / _quarto.yaml file.
          → Treated as the project YAML for its parent directory.
          → This behaves like case (A) except discovery is forced to use
            this YAML file (even if the directory contains multiple YAMLs).

      (E) Any other file-like path.
          → Treated as an atypical case with no YAML.
          → base_dir is input_path.parent.
          → project_yaml = None.
          → file_patterns governs discovery unless explicit_files overrides it.


    ORDER OF OPERATIONS (resolution algorithm):

    1. Normalize and resolve INPUT_PATH:
         input_path = input_path.resolve()

    2. If INPUT_PATH is a directory:
         a. Check for _quarto.yml/_quarto.yaml inside it.
         b. If found → project directory (case A).
         c. If not found → generic directory (case B).
         d. In either case, file_patterns and explicit_files apply normally.

    3. If INPUT_PATH is a .qmd file (case C):
         a. Treat as a one-file project.
         b. base_dir = parent directory.
         c. project_yaml = None.
         d. If user did not supply explicit -f files,
            explicit_files = (input_path,), overriding patterns.

    4. If INPUT_PATH is a YAML file (case D):
         a. Treat it as the project’s main YAML.
         b. base_dir = parent directory.
         c. patterns = file_patterns.
         d. explicit_files override as usual.

    5. Otherwise (case E):
         a. Treat INPUT_PATH as a file within a generic folder.
         b. base_dir = input_path.parent.
         c. project_yaml = None.
         d. patterns = file_patterns.

    6. Return a tuple:
         (base_dir, project_yaml, final_patterns, final_explicit_files)

       Here final_patterns and final_explicit_files encode the correct
       forced precedence rules:
         - explicit_files always override patterns;
         - .qmd input_path without explicit_files forces a single-file
           context and ignores patterns;
         - YAML always takes precedence for discovery unless overridden.


    RETURNS
    -------
    (base_dir, project_yaml, patterns, explicit_files) :
        base_dir : Path
            Directory forming the root of the discovered project.

        project_yaml : Path | None
            The discovered/forced Quarto YAML file, if any.

        patterns : tuple[str, ...]
            Final glob patterns for discovery (possibly empty).

        explicit_files : tuple[Path, ...]
            Final explicit files to include (may be empty).  If non-empty,
            discovery must ignore patterns and YAML.

    """

    input_path = input_path.resolve()

    # Case 1: INPUT_PATH is a directory
    if input_path.is_dir():
        # Check for _quarto.yml/_quarto.yaml directly inside it
        yaml = None
        for name in ("_quarto.yml", "_quarto.yaml"):
            cand = input_path / name
            if cand.exists():
                yaml = cand
                break

        base_dir = input_path
        project_yaml = yaml
        patterns = file_patterns
        return base_dir, project_yaml, patterns, explicit_files

    # Case 2: INPUT_PATH is a single .qmd
    if input_path.suffix.lower() == ".qmd":
        base_dir = input_path.parent
        project_yaml = None
        patterns = ()     # ignore -g unless explicitly desired
        if not explicit_files:
            explicit_files = (input_path,)
        return base_dir, project_yaml, patterns, explicit_files

    # Case 3: INPUT_PATH is a project YAML
    if input_path.name in ("_quarto.yml", "_quarto.yaml"):
        base_dir = input_path.parent
        project_yaml = input_path
        patterns = file_patterns
        return base_dir, project_yaml, patterns, explicit_files

    # Otherwise: treat as directory-like root
    base_dir = input_path.parent
    project_yaml = None
    patterns = file_patterns
    return base_dir, project_yaml, patterns, explicit_files
