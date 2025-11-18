# -*- coding: utf-8 -*-
"""
Consolidate a Quarto project into a single .qmd file.

This tool:

- Discovers the .qmd sources for a project (book, website, etc.).
- For each source, strips its YAML front matter, extracts an optional title,
  and flattens {{< include >}} directives using QuartoTidy's include logic.
- Assembles everything into one big .qmd file with a single YAML header
  at the top and chapter headings for each source file.

By default, per-file YAML front matter is discarded apart from the title,
which becomes a heading. Optionally, the original YAML can be preserved
as commented blocks above each chapter.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .utils import discover_quarto_sources
from .tidy import QuartoTidy


@dataclass
class QuartoConsolidate:
    """
    Consolidate a Quarto project into a single .qmd file.

    Parameters
    ----------
    base_dir :
        Project base directory (root used by discover_quarto_sources).
    project_yaml :
        Optional _quarto.yml / _quarto.yaml path if already known.
    file_patterns :
        Optional glob patterns to filter sources; usually empty for
        book-style projects driven by the project YAML.
    explicit_files :
        Optional explicit list of source files; if non-empty, used in
        preference to project YAML and patterns.
    encoding :
        Text encoding for reading and writing files.
    """

    base_dir: Path
    project_yaml: Path | None = None
    file_patterns: tuple[str, ...] = ()
    explicit_files: tuple[Path, ...] = ()
    encoding: str = "utf-8"

    def consolidate(
        self,
        output_path: Path,
        comment_front_matter: bool = False,
        heading_level: int = 1,
    ) -> Path:
        """
        Consolidate the project into a single .qmd file.

        Parameters
        ----------
        output_path :
            Destination .qmd file; parent directories are created if needed.
        comment_front_matter :
            If True, preserve each file's YAML front matter as a commented
            block above the corresponding chapter heading.
        heading_level :
            Heading level for chapter titles extracted from front matter
            (1 → '#', 2 → '##', etc).

        Returns
        -------
        Path
            The output_path, for convenience.
        """
        sources, project_title = discover_quarto_sources(
            base_dir=self.base_dir,
            encoding=self.encoding,
            project_yaml=self.project_yaml,
            file_patterns=self.file_patterns,
            explicit_files=self.explicit_files,
        )

        qt = QuartoTidy(
            base_dir=self.base_dir,
            project_yaml=self.project_yaml,
            file_patterns=self.file_patterns,
            explicit_files=self.explicit_files,
            encoding=self.encoding,
        )

        # Build top-level YAML: keep it minimal and let _quarto.yml carry
        # the heavy project configuration if present.
        out_lines: list[str] = []
        if project_title is not None:
            out_lines.append("---")
            out_lines.append(f'title: "{project_title}"')
            out_lines.append("---")
            out_lines.append("")
        else:
            # No project title discovered; still keep a stub header for
            # future extension if desired.
            out_lines.append("---")
            out_lines.append("---")
            out_lines.append("")

        for src in sources:
            rel = src.relative_to(self.base_dir)

            # File marker for debugging.
            out_lines.append("")
            out_lines.append(f"<!-- BEGIN FILE: {rel} -->")
            out_lines.append("")

            text = src.read_text(encoding=self.encoding)
            front, _body = qt._split_front_matter(text)

            if comment_front_matter and front:
                out_lines.append(f"<!-- Original front matter from {rel} -->")
                for line in front:
                    out_lines.append(f"<!-- {line} -->")
                out_lines.append(f"<!-- End front matter from {rel} -->")
                out_lines.append("")

            chapter_title = self._extract_title(front)
            if chapter_title:
                hashes = "#" * max(1, heading_level)
                out_lines.append(f"{hashes} {chapter_title}")
                out_lines.append("")

            body_lines = qt._flatten_body(
                path=src,
                recursive=True,
                keep_include_markers=False,
                visited=set(),
            )

            # Strip leading blank lines for tidier joins.
            body_lines = self._strip_leading_blank_lines(body_lines)
            out_lines.extend(body_lines)
            out_lines.append("")
            out_lines.append(f"<!-- END FILE: {rel} -->")
            out_lines.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        text_out = "\n".join(out_lines)
        if text_out and not text_out.endswith("\n"):
            text_out += "\n"
        output_path.write_text(text_out, encoding=self.encoding)
        return output_path

    @staticmethod
    def _extract_title(front: Iterable[str]) -> str | None:
        """
        Extract a 'title: ...' value from a front-matter block.
        """
        for raw in front:
            s = raw.strip()
            if not s.startswith("title:"):
                continue
            _, val = s.split(":", 1)
            title = val.strip()
            # Strip simple surrounding quotes if present.
            if len(title) >= 2 and title[0] == title[-1] and title[0] in ("'", '"'):
                title = title[1:-1]
            return title or None
        return None

    @staticmethod
    def _strip_leading_blank_lines(lines: list[str]) -> list[str]:
        """
        Remove leading blank lines from a list of lines.
        """
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        return lines[i:]
