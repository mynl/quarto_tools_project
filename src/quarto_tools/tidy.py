"""
Tidy, normalize, and report on Quarto .qmd files.

This includes:
- Flattening {{< include >}} directives.
- Normalizing paragraphs, spacing, and comments.
- Reporting: xrefs, citations, python-block inventory.

Python execution is intentionally not handled here. That lives in
pytest_qmd.py as QuartoPyTest.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import re
import textwrap

import pandas as pd

from .utils import discover_quarto_sources
from .xref import QuartoXRefs
from .bibtex import QuartoBibTex, parse_bibtex_text
from .blocks import extract_code_blocks, CodeBlock


INCLUDE_RE = re.compile(
    r"""^\s*\{\{\<\s*include\s+(?P<path>[^>]+?)\s*\>\}\}\s*$"""
)


@dataclass
class QuartoTidy:
    """
    Project-level tidying and reporting for Quarto .qmd files.

    Attributes
    ----------
    base_dir :
        Root directory for the project.
    project_yaml :
        Path to project-level _quarto.yml (optional).
    file_patterns :
        Glob patterns for source discovery.
    explicit_files :
        Explicitly provided files.
    encoding :
        Text encoding for reading files.
    """
    base_dir: Path
    project_yaml: Optional[Path] = None
    file_patterns: tuple[str, ...] = ()
    explicit_files: tuple[Path, ...] = ()
    encoding: str = "utf-8"

    _sources: Optional[List[Path]] = field(default=None, init=False, repr=False)

    # ------------------------
    # Internal helpers
    # ------------------------

    def _discover_sources(self) -> List[Path]:
        """
        Discover .qmd files using the same logic as TOC/XREF/BIBTEX.
        """
        if self._sources is None:
            self._sources, _ = discover_quarto_sources(
                base_dir=self.base_dir,
                encoding=self.encoding,
                project_yaml=self.project_yaml,
                file_patterns=self.file_patterns,
                explicit_files=self.explicit_files,
            )
        return self._sources

    @staticmethod
    def _split_front_matter(text: str) -> tuple[list[str], list[str]]:
        """
        Split a QMD file into (front_matter_lines, body_lines).

        The front matter, if present, is assumed to be a YAML block starting
        at the first line with '---' and ending at the next line that is
        exactly '---'. If no such block exists at the top of the file, the
        front matter list is empty and the body is the full file.
        """
        lines = text.splitlines()
        if not lines:
            return [], []

        if lines[0].strip() != "---":
            return [], lines

        end_idx: Optional[int] = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx is None:
            # Unterminated front matter: treat whole file as body.
            return [], lines

        front = lines[: end_idx + 1]
        body = lines[end_idx + 1 :]
        return front, body

    # ------------------------
    # Feature 1: flatten_file
    # ------------------------

    def flatten_file(
        self,
        main_file: Path,
        output_path: Path,
        recursive: bool = True,
        keep_include_markers: bool = False,
    ) -> Path:
        """
        Flatten {{< include >}} directives in a Quarto file.

        Consider: add flatten_project.

        Parameters
        ----------
        main_file :
            The root .qmd file (absolute or relative to base_dir).
        output_path :
            Destination .qmd file.
        recursive :
            If True, includes inside included files are also expanded.
        keep_include_markers :
            If True, leave commented markers where each include occurred.

        Returns
        -------
        Path
            The path to the written flattened file.
        """
        # originally: TODO INVESTIGATE
        # main_path = main_file
        # if not main_path.is_absolute():
        #     main_path = (self.base_dir / main_path).resolve()

        main_path = Path(main_file)
        if not main_path.exists():
            main_path = (self.base_dir / main_path).resolve()
            assert main_path.exists(), f"Cannot find {main_path.name}"

        text = main_path.read_text(encoding=self.encoding)
        front, _ = self._split_front_matter(text)

        visited: set[Path] = set()
        body_lines = self._flatten_body(
            path=main_path,
            recursive=recursive,
            keep_include_markers=keep_include_markers,
            visited=visited,
        )

        out_lines: list[str] = []
        out_lines.extend(front)
        out_lines.extend(body_lines)

        out = "\n".join(out_lines)
        if out and not out.endswith("\n"):
            out = out + "\n"

        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(out, encoding=self.encoding)

        return output_path

    def _flatten_body(
        self,
        path: Path,
        recursive: bool,
        keep_include_markers: bool,
        visited: set[Path],
    ) -> list[str]:
        """
        Recursively expand include directives for the body of a file.

        The front matter of included files is stripped; only their bodies
        contribute to the output.
        """
        if path in visited:
            # Simple cycle protection: keep the include line as-is at caller.
            return [f"<!-- cyclic include of {path} skipped -->"]

        visited.add(path)
        text = path.read_text(encoding=self.encoding)
        _front, body = self._split_front_matter(text)

        out: list[str] = []

        for raw in body:
            match = INCLUDE_RE.match(raw)
            if not match:
                out.append(raw)
                continue

            include_target = match.group("path").strip().strip("\"'")
            include_path = (path.parent / include_target).resolve()

            if not recursive:
                out.append(raw)
                continue

            if keep_include_markers:
                out.append(f"<!-- BEGIN include {include_target} -->")

            out.extend(
                self._flatten_body(
                    path=include_path,
                    recursive=recursive,
                    keep_include_markers=keep_include_markers,
                    visited=visited,
                )
            )

            if keep_include_markers:
                out.append(f"<!-- END include {include_target} -->")

        visited.remove(path)
        return out

    # ------------------------
    # Feature 2: tidy
    # ------------------------

    def tidy(
        self,
        in_place: bool = True,
        output_dir: Optional[Path] = None,
        remove_comments: bool = False,
        wrap_width: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Normalize formatting of .qmd files.

        Parameters
        ----------
        in_place :
            If True, modify files directly.
        output_dir :
            If provided and in_place is False, write tidied files here with
            mirrored directory structure.
        remove_comments :
            Remove HTML comments <!-- ... --> outside code fences.
        wrap_width :
            If provided, wrap prose paragraphs to this width.

        Returns
        -------
        pandas.DataFrame
            Summary with columns: file, changed, lines_before, lines_after.
        """
        if not in_place and output_dir is None:
            msg = "output_dir must be provided when in_place is False."
            raise ValueError(msg)

        sources = self._discover_sources()
        records: list[dict[str, Any]] = []

        for src in sources:
            text = src.read_text(encoding=self.encoding)
            front, body = self._split_front_matter(text)
            original_lines = text.splitlines()

            tidied_body = self._tidy_body_lines(
                body_lines=body,
                remove_comments=remove_comments,
                wrap_width=wrap_width,
            )

            new_lines: list[str] = []
            new_lines.extend(front)
            new_lines.extend(tidied_body)

            new_text = "\n".join(new_lines)
            if new_text and not new_text.endswith("\n"):
                new_text = new_text + "\n"

            # Normalize original text to have a final newline for comparison.
            original_text_norm = text if text.endswith("\n") else text + "\n"
            changed = new_text != original_text_norm

            records.append(
                {
                    "file": src.relative_to(self.base_dir),
                    "changed": changed,
                    "lines_before": len(original_lines),
                    "lines_after": len(new_lines),
                }
            )

            if not changed:
                continue

            if in_place:
                target_path = src
            else:
                assert output_dir is not None
                rel = src.relative_to(self.base_dir)
                target_path = (output_dir / rel).resolve()
                target_path.parent.mkdir(parents=True, exist_ok=True)

            target_path.write_text(new_text, encoding=self.encoding)

        df = pd.DataFrame.from_records(records)
        return df

    def _tidy_body_lines(
        self,
        body_lines: list[str],
        remove_comments: bool,
        wrap_width: Optional[int],
    ) -> list[str]:
        """
        Tidy only the body (no YAML front matter).

        This function:
          - normalizes blank lines outside code fences,
          - optionally removes HTML comments,
          - optionally wraps paragraphs to a target width,
          - leaves fenced code blocks untouched.
        """
        in_code = False
        tidied: list[str] = []
        pending_paragraph: list[str] = []
        in_html_comment = False

        def flush_paragraph() -> None:
            """
            Flush the current paragraph into tidied, applying wrapping if requested.
            """
            nonlocal pending_paragraph
            if not pending_paragraph:
                return

            if wrap_width is None:
                for line in pending_paragraph:
                    tidied.append(line.rstrip())
            else:
                # Simple paragraph wrapper: join with spaces and re-wrap.
                text = " ".join(s.strip() for s in pending_paragraph)
                wrapped = textwrap.wrap(text, width=wrap_width)
                if not wrapped:
                    tidied.append("")
                else:
                    for wrapped_line in wrapped:
                        tidied.append(wrapped_line)
            pending_paragraph = []

        for raw in body_lines:
            line = raw.rstrip("\n")

            # Detect start/end of fenced code blocks.
            if line.lstrip().startswith("```"):
                # Before switching modes, flush any paragraph we have accumulated.
                if not in_code:
                    flush_paragraph()
                    # Ensure a blank line before a code fence if previous
                    # non-empty line was not blank.
                    if tidied and tidied[-1].strip() != "":
                        tidied.append("")
                in_code = not in_code
                tidied.append(line)
                # After closing a code block, insert a blank line.
                if not in_code:
                    tidied.append("")
                continue

            if in_code:
                tidied.append(line)
                continue

            # Outside code fences: handle optional comment stripping.
            if remove_comments:
                # Handle multi-line HTML comments.
                if in_html_comment:
                    if "-->" in line:
                        in_html_comment = False
                    continue

                if "<!--" in line:
                    # If comment closes on same line, drop the whole line.
                    if "-->" not in line or line.index("-->") < line.index("<!--"):
                        in_html_comment = True
                    continue

            # Normalize whitespace and paragraphs.
            stripped = line.strip()

            if stripped == "":
                # Blank line ends a paragraph.
                flush_paragraph()
                # Avoid multiple consecutive blank lines.
                if tidied and tidied[-1].strip() == "":
                    continue
                tidied.append("")
                continue

            # Headings: ensure a blank line before them.
            if stripped.startswith("#"):
                flush_paragraph()
                if tidied and tidied[-1].strip() != "":
                    tidied.append("")
                tidied.append(stripped)
                continue

            # Normal prose line: accumulate into current paragraph.
            pending_paragraph.append(stripped)

        # Flush any remaining paragraph at end.
        flush_paragraph()

        # Remove trailing blank lines.
        while tidied and tidied[-1].strip() == "":
            tidied.pop()

        return tidied

    # ------------------------
    # Feature 3: report
    # ------------------------

    def report(
        self,
        include_xrefs: bool = True,
        include_bibtex: bool = True,
        include_python: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate a project report: xrefs, citations, python blocks.

        Parameters
        ----------
        include_xrefs :
            Include cross-reference validation.
        include_bibtex :
            Include citation / bibtex analysis.
        include_python :
            Include python-block inventory.

        Returns
        -------
        dict
            Results keyed by 'xrefs', 'bibtex', 'python'.
        """
        results: Dict[str, Any] = {}

        # xrefs
        if include_xrefs:
            xrefs = QuartoXRefs(
                base_dir=self.base_dir,
                project_yaml=self.project_yaml,
                file_patterns=self.file_patterns,
                explicit_files=self.explicit_files,
                encoding=self.encoding,
            )
            results["xrefs"] = xrefs.validate()

        # bibtex
        if include_bibtex:
            bib = QuartoBibTex(
                base_dir=self.base_dir,
                project_yaml=self.project_yaml,
                file_patterns=self.file_patterns,
                explicit_files=self.explicit_files,
                encoding=self.encoding,
            )
            sources = bib._discover_sources()
            citation_keys = bib.collect_citations(sources)
            bib_paths = bib._collect_bib_paths(sources)

            all_rows: list[dict[str, str]] = []
            for bib_path in bib_paths:
                text = bib_path.read_text(encoding=bib.encoding)
                all_rows.extend(parse_bibtex_text(text))

            all_bib_df = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()

            if not all_bib_df.empty and "tag" in all_bib_df.columns:
                all_tags = set(all_bib_df["tag"])
            else:
                all_tags = set()

            missing_citations = sorted(citation_keys - all_tags)
            unused_entries = sorted(all_tags - citation_keys)

            results["bibtex"] = {
                "citation_keys": citation_keys,
                "bib_df": all_bib_df,
                "missing_citations_df": pd.DataFrame({"tag": missing_citations}),
                "unused_bib_entries_df": pd.DataFrame({"tag": unused_entries}),
                "bibtex_paths": bib.bib_paths,
            }

        # python blocks
        if include_python:
            blocks: List[CodeBlock] = []
            sizes: list[dict[str, Any]] = []
            for src in self._discover_sources():
                text = src.read_text(encoding=self.encoding)
                file_blocks = extract_code_blocks(text, src, lang="python")
                blocks.extend(file_blocks)
                sizes.append(
                    {
                        "file": src.relative_to(self.base_dir),
                        "blocks": len(file_blocks),
                    }
                )

            if blocks:
                blocks_df = pd.DataFrame(
                    [
                        {
                            "file": block.file.relative_to(self.base_dir),
                            "block_index": block.block_index,
                            "lang": block.lang,
                            "label": block.label,
                            "caption": block.caption,
                            "start_line": block.start_line,
                            "end_line": block.end_line,
                        }
                        for block in blocks
                    ]
                )
            else:
                blocks_df = pd.DataFrame(
                    columns=[
                        "file",
                        "block_index",
                        "lang",
                        "label",
                        "caption",
                        "start_line",
                        "end_line",
                    ]
                )

            summary_df = pd.DataFrame.from_records(sizes)
            results["python"] = {
                "blocks_df": blocks_df,
                "summary_df": summary_df,
            }

        return results
