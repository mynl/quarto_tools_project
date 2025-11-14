# -*- coding: utf-8 -*-
"""
Create TikZ Table of Contents from a Quarto project, with:
- copious debug comments and whitespace for readability,
- chapter header baseline alignment,
- look-ahead chapter cache to decide row wrapping by remaining column capacity.

Windows usage (example):
  python -m quarto_tools.toc C:\\path\\to\\quarto\\project C:\\out\\toc.tex
"""

import math
import re
import subprocess
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path
from typing import Any, Dict, List, Tuple

import click
import pandas as pd

from .utils import (discover_quarto_sources, extract_front_matter,
                    strip_code_blocks, git_info)


@dataclass
class QuartoToc:
    """
    Build a five-level TikZ TOC from a Quarto project or file.

    Levels:
      - Title: large bold title on top left of page; with date time stamp and github info if available
      - Chapters: bold, shaded box at top of each column, with ch #
      - Sections: ch.sec Numbered, roman font
      - Subsections: bulleted separated paragraph below section
      - Subsubsection: comma separated list within parenthesis within subsections

    Key features:
      - Baseline-aligned chapter headers (anchor=base west; chapter→chapter chaining via .base east).
      - Subsection balancing into subcolumns by height.
      - Look-ahead chapter cache to decide row wrapping by remaining subcolumn capacity.
      - Optional verbose debug mode that emits clear LaTeX comments and structure.

    Parameters:
        base_dir:
            Root Quarto directory or single .qmd/.qmd-tree to parse.

        max_levels:
            Maximum heading depth to include. -1 means full depth; 1 gives
            chapters only; 2 gives chapters and sections; etc.

        up_level:
            If true, promote the highest heading level found so that (for
            example) ### becomes a chapter level.

        omit_titles:
            Set of titles to exclude when building the TOC.

        chapter_min_height:
            Minimum height of the chapter header box; "auto" computes a value
            based on title length.

        section_max_height:
            Maximum height of a section subcolumn (e.g., "6cm"). Sections wrap
            across subcolumns when this cap is exceeded.

        max_columns_per_row:
            Total subcolumn capacity per row before forcing a wrap.

        balance_mode:
            Subcolumn packing rule: "stable" respects document order; "ffd"
            uses first-fit decreasing by estimated height.

        title_gap:
            Vertical gap between the title bar and the first row of chapters.

        section_top_gap:
            Vertical gap between a chapter header and the first section node.

        column_width:
            Width of each chapter column.

        column_gap:
            Horizontal gap between chapter groups.

        section_column_gap:
            Horizontal gap between section subcolumns within one chapter.

        row_gap:
            Vertical gap between rows.

        title_col, chapter_col, section_col, subsection_col:
            DataFrame column names used during parsing and layout.

        chars_per_cm_title, chars_per_cm_subs:
            Heuristics used to estimate line counts in title and subsection
            text.

        baseline_large_pt, baseline_norm_pt, baseline_subs_pt:
            Baseline skips (in points) for chapter headers, section titles,
            and subsections.

        subs_linespread:
            Multiplicative line spacing used for subsection text.

        top_prefix_lines:
            Number of prefix lines reserved in the chapter header (e.g., “Ch NN”).

        padding_pt:
            Inner padding around chapter header nodes.

        gap_pt:
            Vertical gap between section title and subsection block.

        inner_sep_section_pt:
            Inner padding for section nodes.

        encoding:
            File-reading encoding.

        trust_tex:
            If true, skip escaping LaTeX specials and trust the input text.

        debug:
            If true, emit LaTeX comments and light node outlines to help visualize
            layout and alignment.

        project_yaml:
            Explicit _quarto.yml / .yaml, if not under base_dir

        file_patterns:
            Glob patterns relative to base_dir (e.g., ("*.qmd", "posts/*.qmd"))

        explicit_files:
            Explicit QMD files; takes precedence over patterns/project_yaml

        use_yaml_title_as_chapter:
            If no level-1 heading in a file, use its front-matter title as a synthetic chapter

    """
    # Inputs
    base_dir: Path

    # Layout and parsing options
    max_levels: int = -1                         # how many levels to use, -1 = all levels, 1 = chapter only, 2 = chapter / section etc.
    up_level: bool = False                       # If true, then adjust levels so that the highest level found (eg ###) becomes treated as chapters (#)
    omit_titles: set | None = None
    chapter_min_height: str | None = "auto"      # height of chapter name box
    section_max_height: str | None = "6cm"       # cap for subcolumn height; sections wrap across subcolumns
    max_columns_per_row: int | None = None       # Row capacity (preferred): number of subcolumns per row.
    balance_mode: str = "stable"                 # "stable" or "ffd" (first-fit decreasing)

    # Column and gap geometry
    title_gap: str = "4mm"                       # gap from titlebar to to of toc
    section_top_gap: str = "1.5mm"               # vertical gap from chapter box to first section column
    column_width: str = "5cm"                    # width of each chapter column
    column_gap: str = "3mm"                      # gap between chapter groups
    section_column_gap: str = "3mm"              # gap between section subcolumns
    row_gap: str = "5mm"                         # vertical gap between rows

    # Dataframe column names - largely redundant
    title_col: str = "title"
    chapter_col: str = "chapter"
    section_col: str = "section"
    subsection_col: str = "subsection"

    # Text metrics (rough heuristics)
    chars_per_cm_title: float = 7.5
    chars_per_cm_subs: float = 8.8
    baseline_large_pt: float = 14.5
    baseline_norm_pt: float = 12.0
    baseline_subs_pt: float = 8.5
    subs_linespread: float = 0.8
    top_prefix_lines: int = 1                    # line for "Ch NN" in heading
    padding_pt: float = 8.0                      # inner sep for chapter nodes
    gap_pt: float = 1.0                          # between title and subs for sections
    inner_sep_section_pt: float = 6.0            # inner sep for section nodes
    encoding: str = "utf-8"                      # for reading files

    # Meta
    trust_tex: bool = True                       # stops using _escape_latex
    debug: bool = False                          # Emit comments and faint boxes for debugging/reading

    # NEW
    # Source discovery and file-level options
    project_yaml: Path | None = None             # explicit _quarto.yml / .yaml, if not under base_dir
    file_patterns: tuple[str, ...] = ()          # glob patterns relative to base_dir (e.g., ("*.qmd", "posts/*.qmd"))
    explicit_files: tuple[Path, ...] = ()        # explicit QMD files; takes precedence over patterns/project_yaml
    use_yaml_title_as_chapter: bool = True       # if no level-1 heading in a file, use its front-matter title as a synthetic chapter

    LATEX_SPECIALS = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    # Internal state
    def __post_init__(self) -> None:
        self._df: pd.DataFrame | None = None
        self.base_dir = Path(self.base_dir)
        self.out_path: Path | None = None
        # default title; may be overridden from _quarto.yml in project mode
        self.title = "Table of Contents"
        # chapter layout cache: chapter_index -> dict with columns, slots, title, etc.
        self._chapter_cache: Dict[int, Dict[str, Any]] = {}

    # properties
    @property
    def df(self):
        if self._df is None:
            self._df = self.make_df()
        return self._df

    # ---------- Data extraction ----------

    def make_df(self) -> pd.DataFrame:
        """
        Extract headings from Quarto sources and build the layout DataFrame.

        Sources can come from:
          - a Quarto project YAML (_quarto.yml / _quarto.yaml),
          - one or more explicit .qmd files,
          - glob patterns under base_dir.

        Applies omit_titles and computes chapter/section/subsection counters,
        including:
          - optional "up-level" of files with no level-1 headings, and
          - optional synthetic chapter rows from per-file YAML titles.
        """
        sources, project_title = discover_quarto_sources(
            base_dir=self.base_dir,
            encoding=self.encoding,
            project_yaml=self.project_yaml,
            file_patterns=self.file_patterns,
            explicit_files=self.explicit_files,
        )
        if project_title is not None:
            self.title = project_title

        click.echo(f"Discovered {len(sources)} source file(s).")

        outlines: list[tuple[int, str | None, list[tuple[int, str, str | None, int]]]] = []
        for file_index, path in enumerate(sources):
            doc_title, headings = self._parse_file(path)
            outlines.append((file_index, doc_title, headings))

        rows: list[list[Any]] = []

        for file_index, doc_title, headings in outlines:
            if not headings:
                continue

            levels = [h[0] for h in headings]
            has_level1 = any(l == 1 for l in levels)

            if has_level1:
                # file already has explicit chapter-level headings
                for level, title, refs, _order in headings:
                    rows.append([level, title, "" if refs is None else refs])
            else:
                # no level-1 headings in this file
                if self.use_yaml_title_as_chapter and doc_title:
                    # synthetic chapter row from per-file YAML title
                    rows.append([1, doc_title, ""])
                    for level, title, refs, _order in headings:
                        rows.append([level, title, "" if refs is None else refs])
                elif self.up_level:
                    # shift smallest heading level down to 1 (per file)
                    min_level = min(levels)
                    shift = max(0, min_level - 1)
                    for level, title, refs, _order in headings:
                        new_level = max(1, level - shift)
                        rows.append([new_level, title, "" if refs is None else refs])
                else:
                    # leave as-is; first heading will behave like a chapter in the existing scheme
                    for level, title, refs, _order in headings:
                        rows.append([level, title, "" if refs is None else refs])

        df = pd.DataFrame(rows, columns=["level", "title", "refs"])

        if self.omit_titles:
            df = df.query("title not in @self.omit_titles").copy()

        df["chapter"] = [i - 1 for i in accumulate(df.level, lambda a, x: a + (x == 1))]
        df["section"] = [
            i
            for i in accumulate(
                df.level,
                lambda a, x: 0 if x == 1 else a + (x == 2),
                initial=0,
            )
        ][1:]
        df["subsection"] = [
            i
            for i in accumulate(
                df.level,
                lambda a, x: 0 if x <= 2 else a + (x == 3),
                initial=0,
            )
        ][1:]
        df["subsubsection"] = [
            i
            for i in accumulate(
                df.level,
                lambda a, x: 0 if x <= 3 else a + (x == 4),
                initial=0,
            )
        ][1:]

        return df

    def _original_make_df(self) -> pd.DataFrame:
        """
        Extract headings levels 1..4 from a Quarto project.
        Applies omit_titles, computes chapter/section/subsection counters.
        """
        yaml_path = None
        if (self.base_dir / "_quarto.yml").exists():
            yaml_path = self.base_dir / "_quarto.yml"
        elif (self.base_dir / "_quarto.yaml").exists():
            yaml_path = self.base_dir / "_quarto.yaml"
        else:
            raise ValueError("Cannot find _quarto file.")

        yaml_split = yaml_path.read_text(encoding=self.encoding).split("\n")

        # extract the title
        for line in yaml_split:
            line = line.strip()
            if line.startswith('title:'):
                title = line[7:].strip()
                if title[0] == '"' or title[0] == "'":
                    title = title[1:]
                if title[-1] == '"' or title[-1] == "'":
                    title = title[:-1]
                self.title = title

        chs: Dict[str, str] = {}
        for line in yaml_split[yaml_split.index("  chapters:") + 1:]:
            if line.startswith("    - "):
                fn = line[6:]
                part_file_path = self.base_dir / fn
                chs[fn] = part_file_path.read_text(encoding=self.encoding)
                includes = [i for i in chs[fn].split("\n") if i.startswith("{{< include ")]
                for i in includes:
                    inc = i[12:-4]  # {{< include 020-files/finance.qmd >}}
                    include_path = part_file_path.parent / inc
                    chs[f"posts/{inc}"] = include_path.read_text(encoding=self.encoding)
            else:
                break

        sects: Dict[str, List[List[str | Any]]] = {}
        rec = re.compile(r"^(?<!#\|)(#{1,}) (.*?)(?:$| (\{.*\})$)")
        incode_rex = re.compile(r"^```|<!\-\-|\-\->|<!\-\-.*?\-\->")

        for k, v in chs.items():
            sects[k] = []
            incode = False
            for line in v.split("\n"):
                for _ in incode_rex.findall(line):
                    incode = not incode
                if incode:
                    continue
                m = rec.match(line)
                if m:
                    sects[k].append([m[1], m[2], m[3]])

        rows: List[List[Any]] = []
        for f in sects.values():
            rows.extend(
                [[len(level), title, "" if refs is None else refs[1:-1]] for level, title, refs in f]
            )

        df = pd.DataFrame(rows, columns=["level", "title", "refs"])

        if self.omit_titles:
            df = df.query("title not in @self.omit_titles").copy()

        df["chapter"] = [i - 1 for i in accumulate(df.level, lambda a, x: a + (x == 1))]
        df["section"] = [i for i in accumulate(df.level, lambda a, x: 0 if x == 1 else a + (x == 2), initial=0)][1:]
        df["subsection"] = [i for i in accumulate(df.level, lambda a, x: 0 if x <= 2 else a + (x == 3), initial=0)][1:]
        df["subsubsection"] = [i for i in accumulate(df.level, lambda a, x: 0 if x <= 3 else a + (x == 4), initial=0)][1:]

        return df

    # ---------- TikZ emission ----------

    def make_tikz_toc(self, chapter_number: int = -1) -> str:
        """
        Create a TikZ picture of the TOC with baseline-aligned chapter headers
        and look-ahead row wrapping by subcolumn capacity.

        If chapter_number > 0 then up-level everything to produce a
        more detailed table for that chapter.
        """
        # subset for levels
        if self.max_levels > -1:
            w = self.df.query(f"level <= {self.max_levels}").copy()
        else:
            w = self.df.copy()

        if chapter_number > 0:
            w = w.query(f'{self.chapter_col} == {chapter_number}')
            # "up level"
            ch_row = w.query('level == 1').index[0]
            uplevel_chapter_name = f"Chapter {w.loc[ch_row, 'chapter']}. {w.loc[ch_row, 'title']}"
            w = w.drop(index=ch_row)
            w.level = w.level - 1
            w['chapter'] = w['section']
            w['section'] = w['subsection']
            w['subsection'] = w['subsubsection']
            w['subsubsection'] = pd.NA

        # this is silly to do - was a way to detect chapter headings but better to use level
        for col in (self.section_col, self.subsection_col):
            if col in w.columns:
                w[col] = w[col].replace(0, pd.NA)

        w = w.sort_values([self.chapter_col, self.section_col, self.subsection_col], kind="mergesort")

        # Infer minimum chapter height if auto
        if self.chapter_min_height in (None, "auto"):
            chap_titles = (
                w[w[self.section_col].isna() & w[self.subsection_col].isna()][self.title_col]
                .astype(str)
                .tolist()
            )
            if not chap_titles:
                chap_titles = w.groupby(self.chapter_col, sort=True)[self.title_col].first().astype(str).tolist()
            self.chapter_min_height = self._estimate_chapter_min_height_cm(chap_titles)

        # Pre-compute per-chapter layouts and cache them
        self._chapter_cache.clear()
        for ch_val, ch_df in w.groupby(self.chapter_col, sort=True):
            ch_idx = int(ch_val) if self._is_int_like(ch_val) else int(ch_val)
            self._chapter_cache[ch_idx] = self._compute_chapter_layout(ch_idx, ch_df, chapter_number)

        # Row capacity in subcolumns
        row_capacity = self.max_columns_per_row if self.max_columns_per_row else 999999

        out: List[str] = []
        out.append("\\begin{tikzpicture}[node distance=2mm]")
        out.append("  % requires: \\usetikzlibrary{calc,positioning,fit}")
        out.append("  \\tikzset{")

        out.append(
            f"    tocChapterBox/.style={{draw={'red!10' if self.debug else 'none'}, "
            f"fill=black!7, inner sep=6pt, outer sep=0pt, "
            f"align=left, text width={self.column_width}, minimum height={self.chapter_min_height}}},"
        )
        out.append(
            f"    tocSectionBox/.style={{draw={'blue!10' if self.debug else 'none'}, "
            f"inner sep=3pt, outer sep=0pt, text ragged, text width={self.column_width}}},"
        )
        out.append("    tocGroupBox/.style={draw=none, inner sep=0pt},")
        out.append("    tocRowBox/.style={draw=none, inner sep=0pt}")
        out.append("  }")
        out.append("")

        # prepare for the title
        if chapter_number > 0:
            title = uplevel_chapter_name
        else:
            title = getattr(self, "title", "Table of Contents")
        commit, state = git_info(self.base_dir)
        dt = self._now_iso()
        # --- Title Bar Node ---
        out.append("% --- Title Bar Node ---")
        out.append("  % Top-left anchored title; spans the full \\textwidth")
        out.append("  \\node[anchor=north west, inner sep=0pt, text width=\\textwidth] (titlebar) at (0,0) {")
        out.append("    \\hbox to\\textwidth{%")
        out.append("         \\vtop{\\hsize=.68\\textwidth")
        out.append(f"              \\Large\\bfseries {title}\\par")
        out.append("         }%")
        out.append("         \\hfill")
        out.append("         \\vtop{\\hsize=.32\\textwidth")
        out.append(f"              \\raggedleft\\footnotesize {dt} \\\\")
        out.append(f"              \\ttfamily {commit} --- {state}\\par")
        out.append("         }%")
        out.append("    }%")
        out.append("    \\vspace{2mm}\\hrule\\vspace{4mm}\\par")
        out.append("  };")
        out.append("")

        # Row origins: align chapter SOUTH edges to this line
        out.append("  % Row origins: first row line sits just below the title bar")
        out.append(f"  \\coordinate (rowOrigin0) at ($ (titlebar.south west) + (0,-{self.title_gap}-{self.chapter_min_height}) $);")
        out.append("")

        if self.debug:
            out.append(
                f"  \\draw[densely dotted, gray!60] ($(rowOrigin0)+(-3mm,0)$) "
                f"-- ($(rowOrigin0)+(22cm,0)$);"
            )

        current_row = 0
        remaining_slots = row_capacity
        last_group_node: str | None = None
        last_chapter_node: str | None = None
        row_group_names: List[str] = []

        # Emit chapters in order, using cached layout and row slot accounting
        ch_counter = 0
        for ch_val in sorted(self._chapter_cache.keys()):
            ch_counter += 1
            cache = self._chapter_cache[ch_val]
            slots_needed = cache["slots"]
            ch_node = cache["chapter_node_name"]  # e.g., "c1-chap"
            group_node = cache["group_node_name"]
            col_tag = cache["col_tag"]
            ch_text = cache["chapter_text"]
            section_columns = cache["columns"]

            # Row break if needed by look-ahead
            if remaining_slots < slots_needed:
                # close previous row
                if row_group_names:
                    row_fit = f"rowFit{current_row}"
                    parts = " ".join(f"({g})" for g in row_group_names)
                    out.append(f"  % ---- close row {current_row} ----")
                    out.append(f"  \\node[tocRowBox, fit={{ {parts} }}] ({row_fit}) {{}};")
                    out.append(
                        f"  \\coordinate (rowOrigin{current_row + 1}) at ($({row_fit}.south west)+(0,-{self.chapter_min_height}-{self.row_gap})$);"
                    )
                    if self.debug:
                        out.append(
                            f"  \\draw[densely dotted, gray!60] ($(rowOrigin{current_row + 1})+(-3mm,0)$) "
                            f"-- ($(rowOrigin{current_row + 1})+(22cm,0)$);"
                        )
                    out.append("")
                current_row += 1
                remaining_slots = row_capacity
                last_group_node = None
                last_chapter_node = None
                row_group_names = []

            # Chapter banner comment
            if self.debug:
                out.append(f"  % =============================================================")
                out.append(f"  % Chapter {ch_val:02d}: {cache['chapter_title']}")
                out.append(f"  % Estimated subcolumns: {slots_needed}")
                out.append(f"  % =============================================================")
                out.append("")

            # Place chapter header baseline-aligned.
            if (last_group_node is None) or (last_chapter_node is None):
                # first chapter in row sits with its SOUTH edge on the row line
                out.append(
                    f"  \\node[tocChapterBox, anchor=south west] ({ch_node}) "
                    f"at (rowOrigin{current_row}) {{{ch_text}}};"
                )
            else:
                # x from previous GROUP's east (full width), y from current row's line
                out.append(
                    "  \\node[tocChapterBox, anchor=south west] "
                    f"({ch_node}) at ($({last_group_node}.east|-rowOrigin{current_row})+({self.column_gap},0)$) "
                    f"{{{ch_text}}};"
                )
            out.append("")
            last_chapter_node = ch_node



            # Place section subcolumns (if any), aligned under the chapter header
            section_nodes: List[str] = []
            if section_columns:
                first_col_top = None
                prev_col_top = None

                if self.debug:
                    for ci, col_items in enumerate(section_columns):
                        heights = [f"{h:.2f}cm" for (_, _, h, _) in col_items]
                        out.append(f"  % Column {ci} has {len(col_items)} sections; est heights: {', '.join(heights)}")
                    out.append("")

                for col_i, col_items in enumerate(section_columns):
                    # First column starts from the chapter node's south west edge, not "below=of",
                    # so it's independent of the chapter text baseline and always grows downward.
                    if col_i == 0:
                        start_placement = f"at ($({ch_node}.south west)+(0,-{self.section_top_gap})$)"
                        first_anchor = ", anchor=north west"
                    else:
                        start_placement = f"at ($({prev_col_top}.north east)+({self.section_column_gap},0)$)"
                        first_anchor = ", anchor=north west"

                    prev_in_col = None
                    col_top_node = None

                    for (sec_val, node_text, _est_h_cm, _ord) in col_items:
                        sec_suffix = self._safe_int_str(sec_val)
                        sec_node = f"{col_tag}-sec-{sec_suffix}-col{col_i}"

                        if prev_in_col is None:
                            out.append(
                                f"  \\node[tocSectionBox{first_anchor}] ({sec_node}) {start_placement} "
                                f"{{{node_text}}}; % first in column {col_i}"
                            )
                            col_top_node = sec_node
                            prev_in_col = sec_node
                            if col_i == 0:
                                first_col_top = sec_node
                                prev_col_top = sec_node
                        else:
                            out.append(
                                f"  \\node[tocSectionBox] ({sec_node}) [below=of {prev_in_col}] "
                                f"{{{node_text}}};"
                            )
                            prev_in_col = sec_node

                        section_nodes.append(sec_node)

                    if col_top_node is not None:
                        prev_col_top = col_top_node

                out.append("")

            # Fit node around chapter header + its sections
            parts = " ".join([f"({ch_node})"] + [f"({n})" for n in section_nodes]) if section_nodes else f"({ch_node})"
            out.append(f"  \\node[tocGroupBox, fit={{ {parts} }}] ({group_node}) {{}};")
            out.append("")

            # Update trackers for row composition
            remaining_slots -= slots_needed
            last_group_node = group_node
            row_group_names.append(group_node)

        # Close final row neatly
        if row_group_names:
            row_fit = f"rowFit{current_row}"
            parts = " ".join(f"({g})" for g in row_group_names)
            out.append(f"  % ---- close row {current_row} ----")
            out.append(f"  \\node[tocRowBox, fit={{ {parts} }}] ({row_fit}) {{}};")
            out.append("")

        out.append("\\end{tikzpicture}")
        return "\n".join(out)

    def write_tikz(self, out_path: Path | str, chapter_number: int = -1) -> None:
        """
        Write bare TikZ code to a .tex snippet file.
        """
        tikz_code = self.make_tikz_toc(chapter_number)
        self._safe_save(out_path, tikz_code)

    def write_tex(self, out_path: Path | str, chapter_number: int = -1) -> None:
        """
        Wrap the TikZ picture into a standalone LuaLaTeX document and save.
        """
        tikz_code = self.make_tikz_toc(chapter_number)
        tex_code = self._wrap_tikz_to_tex(tikz_code)
        self._safe_save(out_path, tex_code)

    @staticmethod
    def run_lualatex(tex_path: Path) -> None:
        """
        Run lualatex on tex_path and stream stdout/stderr.
        """
        subprocess.run(
            ["lualatex", "-interaction=nonstopmode", str(tex_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    # ---------- Helpers ----------

    @staticmethod
    def _is_int_like(x: Any) -> bool:
        try:
            int(x)
            return True
        except Exception:
            return False

    @staticmethod
    def _safe_int_str(x: Any) -> str:
        try:
            return str(int(x))
        except Exception:
            return str(x)

    def _cm_from(self, spec: str | None, default_cm: float) -> float:
        """
        Parse '<num>cm' or '<num>mm' into centimeters; fallback to default_cm.
        """
        if spec is None:
            return default_cm
        m = re.fullmatch(r"\s*([\d.]+)\s*(cm|mm)\s*", str(spec))
        if not m:
            return default_cm
        val = float(m.group(1))
        return val if m.group(2) == "cm" else val / 10.0

    def _estimate_lines(self, text: str, width_cm: float, chars_per_cm: float) -> int:
        """
        Rough line-count estimator given width and average characters per cm.
        """
        return max(1, math.ceil(len(text) / max(1e-6, chars_per_cm * width_cm)))

    def _estimate_section_height_cm(self, sec_title: str, subs_text: str | None, width_cm: float) -> float:
        """
        Rough section-node height estimate in cm, combining title and inline subsections.
        """
        # title
        title_lines = self._estimate_lines(sec_title, width_cm, self.chars_per_cm_title)
        h_title_pt = title_lines * self.baseline_norm_pt

        # subs
        if subs_text:
            subs_lines = self._estimate_lines(subs_text, width_cm, self.chars_per_cm_subs)
            h_subs_pt = subs_lines * self.baseline_subs_pt * self.subs_linespread
            h_gap_pt = self.gap_pt
        else:
            h_subs_pt = 0.0
            h_gap_pt = 0.0

        h_pad_pt = self.inner_sep_section_pt
        return (h_title_pt + h_gap_pt + h_subs_pt + h_pad_pt) * 0.03514598  # pt -> cm

    def _estimate_chapter_min_height_cm(self, titles: List[str]) -> str:
        """
        Estimate min-height for \\large chapter nodes and return as '<X>cm'.
        """
        m = re.fullmatch(r"\s*([\d.]+)\s*cm\s*", self.column_width)
        width_cm = float(m.group(1)) if m else 5.0
        max_lines = 1
        for t in titles:
            n = max(1, math.ceil(len(t) / (self.chars_per_cm_title * width_cm)))
            max_lines = max(max_lines, n + self.top_prefix_lines)
        height_pt = max_lines * self.baseline_large_pt + self.padding_pt
        height_cm = height_pt * 0.03514598
        return f"{height_cm * 1.08:.2f}cm"

    def _escape_latex(self, value: object) -> str:
        """
        Escape LaTeX specials for safe node text.
        """
        s = "" if value is None else str(value)
        if self.trust_tex:
            return self._markdown_to_tex(s)
            # return s
        out: List[str] = []
        for ch in s:
            out.append(cls.LATEX_SPECIALS.get(ch, ch))
        return "".join(out)

    def _wrap_tikz_to_tex(self, tikz: str) -> str:
        """
        Wrap the TikZ picture into a minimal standalone LuaLaTeX document,
        with a top title bar: left = self.title, right = ISO datetime on top,
        and 'commit --- state' beneath, flush right.
        """

        tex = f"""\\documentclass[10pt, border=5mm]{{standalone}}

% LuaLaTeX fonts
\\usepackage{{fontspec}}
\\setmainfont{{Stix Two Text}}
\\usepackage{{unicode-math}}
\\setmathfont{{Stix Two Math}}

\\usepackage{{xcolor}}
\\usepackage{{url}}

% TikZ
\\usepackage{{tikz}}
\\usetikzlibrary{{calc,positioning,fit}}

% small helpers
\\newcommand{{\\I}}{{\\vphantom{{lp}}}}

\\begin{{document}}

{tikz}

\\end{{document}}
"""
        return tex

    def _safe_save(self, out_path: Path | str, text: str) -> None:
        """
        Ensure parent dir exists and write UTF-8 text.
        """
        p = Path(out_path)
        self.out_path = p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding=self.encoding)

    # ---------- Column packing ----------

    def _columns_by_height(
        self, items: List[Tuple[str, str, float, int]], cap_cm: float, mode: str = "stable"
    ) -> List[List[Tuple[str, str, float, int]]]:
        """
        Partition (sec_val, node_text, est_h_cm, order_idx) into subcolumns.

        mode:
          - "stable": keep original order; wrap to next column when cap exceeded.
          - "ffd":    first-fit decreasing by height, then restore original order within each column.
        """
        if not items:
            return [[]]

        if cap_cm <= 0 or math.isinf(cap_cm):
            return [sorted(items, key=lambda t: t[3])]

        if mode == "ffd":
            total = sum(h for _, _, h, _ in items)
            k = max(1, math.ceil(total / cap_cm))
            cols = [[] for _ in range(k)]
            heights = [0.0] * k
            for it in sorted(items, key=lambda t: t[2], reverse=True):
                j = min(range(k), key=lambda c: heights[c])
                cols[j].append(it)
                heights[j] += it[2]
            return [sorted(col, key=lambda t: t[3]) for col in cols]

        # stable greedy wrap
        cols: List[List[Tuple[str, str, float, int]]] = []
        cur: List[Tuple[str, str, float, int]] = []
        h = 0.0
        for it in sorted(items, key=lambda t: t[3]):
            est = it[2]
            if cur and h + est > cap_cm:
                cols.append(cur)
                cur, h = [], 0.0
            cur.append(it)
            h += est
        if cur:
            cols.append(cur)
        return cols

    # ---------- Chapter look-ahead ----------

    def _compute_chapter_layout(self, ch_idx: int, ch_df: pd.DataFrame, chapter_number: int) -> Dict[str, Any]:
        """
        Compute and cache a chapter's:
          - chapter header text,
          - per-section display text and height estimates,
          - subcolumn packing and 'slots' needed,
          - stable names for nodes to refer to during emission.
        """
        col_tag = f"c{ch_idx}"
        ch_node = f"{col_tag}-chap"
        group_node = f"{col_tag}-group"

        # Chapter title
        # ch_title_row = ch_df[ch_df[self.section_col].isna() & ch_df[self.subsection_col].isna()]
        # chapter_title = (
        #     self._escape_latex(ch_title_row.iloc[0][self.title_col])
        #     if not ch_title_row.empty
        #     else self._escape_latex(ch_df.iloc[0][self.title_col])
        # )
        hdr = ch_df.query("level == 1")
        if not hdr.empty:
            raw_title = hdr.iloc[0][self.title_col]
        else:
            raw_title = ch_df.iloc[0][self.title_col]  # fallback
        chapter_title = self._markdown_to_tex(raw_title)
        ch_prefix = f"{'Sec' if chapter_number > 0 else 'Ch'} {ch_idx:02d}\\\\ " if ch_idx > 0 else "\\\\ "
        ch_text = f"{ch_prefix}\\large\\bfseries {chapter_title}"

        # Sections for this chapter - this is where we use 0->n/a for ignored sections
        body = ch_df[ch_df[self.section_col].notna()]
        section_columns: List[List[Tuple[str, str, float, int]]] = []

        if not body.empty:
            sections = [(sec_val, grp) for sec_val, grp in body.groupby(self.section_col, sort=False)]
            width_cm = self._cm_from(self.column_width, 5.0)
            cap_cm = self._cm_from(self.section_max_height, math.inf) if self.section_max_height else math.inf

            # do not number for prefix - ch 0
            numbered_sections = (ch_idx > 0)

            sec_items: List[Tuple[str, str, float, int]] = []
            for ord_idx, (sec_val, sec_block) in enumerate(sections):
                sec_title_row = sec_block[sec_block[self.subsection_col].isna()]
                sec_title = (
                    self._escape_latex(sec_title_row.iloc[0][self.title_col])
                    if not sec_title_row.empty
                    else self._escape_latex(sec_block.iloc[0][self.title_col])
                )

                # label prefix per rule
                label = f"{ch_idx}.{self._safe_int_str(sec_val)} " if numbered_sections else ""

                subs = sec_block[sec_block[self.subsection_col].notna()]
                if not subs.empty:
                    if 1 <= self.max_levels <= 3:
                        bullets = " $\\bullet$ ".join(self._escape_latex(t) for t in subs[self.title_col].tolist())
                    else:
                        # includes level 4, want different treatment
                        # Split into level-3 and level-4; preserve original row order
                        lvl3 = subs.query("level == 3")
                        lvl4 = subs.query("level == 4")

                        bullet_parts: list[str] = []

                        for _, row3 in lvl3.iterrows():
                            sub_id = row3[self.subsection_col]

                            # main level-3 title
                            txt3 = self._escape_latex(row3[self.title_col])

                            # any level-4 children with the same subsection id, in original order
                            children = lvl4[lvl4[self.subsection_col] == sub_id][self.title_col].tolist()
                            if children:
                                child_str = ", ".join(self._escape_latex(t) for t in children)
                                txt3 = f"{txt3} ({child_str})"

                            bullet_parts.append(txt3)

                        # final bullet string for this section
                        bullets = " $\\bullet$ ".join(bullet_parts)

                    # write out, tight, sans, italic, explicit fontsize to stabilize baseline skips
                    tight = "{\\fontsize{8}{6.0}\\selectfont\\rmfamily\\itshape " + bullets + "}"
                    node_text = f"{label} {sec_title}\\\\[1pt]{tight}"
                    subs_text = bullets
                else:
                    node_text = f"{label} {sec_title}"
                    subs_text = None

                est_h_cm = self._estimate_section_height_cm(sec_title, subs_text, width_cm)
                sec_items.append((str(sec_val), node_text, est_h_cm, ord_idx))

            section_columns = self._columns_by_height(sec_items, cap_cm, mode=self.balance_mode)

        # How many subcolumns (slots) does this chapter need?
        slots = max(1, len(section_columns)) if section_columns else 1

        return {
            "chapter_index": ch_idx,
            "chapter_title": chapter_title,
            "chapter_text": ch_text,
            "columns": section_columns,
            "slots": slots,
            "group_node_name": group_node,
            "chapter_node_name": ch_node,
            "col_tag": col_tag,
        }

    def _now_iso(self) -> str:
        """
        Current local datetime formatted as ISO 'YYYY-MM-DD HH:MM:SS'.
        """
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _markdown_to_tex(self, text: str) -> str:
        """
        Convert minimal Markdown syntax to TeX equivalents for headings:
          **bold** → \\textbf{...}
          *italic* or _italic_ → \\textit{...}
          `code` → \\texttt{...}
        Leaves existing TeX ($...$, \\mathsf{}, etc.) untouched.
        Escapes only dangerous specials outside math mode.

        This is quite tricky! The protect_math stores math in a dict,
        then adjusts, then puts back.
        """
        s = text

        # protect inline math $...$ and LaTeX commands \foo
        math_spans = {}
        def protect_math(m):
            key = f"@@M{len(math_spans)}@@"
            math_spans[key] = m.group(0)
            return key
        s = re.sub(r"\$[^$]+\$", protect_math, s)

        # basic markdown replacements
        s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)   # **bold**
        s = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", s)       # *italic*
        s = re.sub(r"_([^_]+)_", r"\\textit{\1}", s)         # _italic_
        s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)         # `code`

        # escape specials that are still unprotected
        specials = {
            "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",  # underscore if not italics marker
            # "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        }
        s = "".join(specials.get(ch, ch) for ch in s)

        # restore math spans
        for key, val in math_spans.items():
            s = s.replace(key, val)

        return s


    def _parse_file(self, path: Path) -> tuple[str | None, list[tuple[int, str, str | None, int]]]:
        """
        Parse a single QMD file:
          - extract optional front-matter title,
          - collect headings (raw level, title, refs, order_in_file) from body.
        """
        text = path.read_text(encoding=self.encoding)
        doc_title, body_lines, _meta = extract_front_matter(text)
        body_lines = strip_code_blocks(body_lines)

        rec = re.compile(r"^(?<!#\|)(#{1,}) (.*?)(?:$| (\{.*\})$)")

        headings: list[tuple[int, str, str | None, int]] = []
        order = 0

        for line in body_lines:
            m = rec.match(line)
            if not m:
                continue
            level_marks, title, refs = m[1], m[2], m[3]
            level = len(level_marks)
            clean_refs = None
            if refs is not None:
                clean_refs = refs[1:-1]
            headings.append((level, title, clean_refs, order))
            order += 1

        return doc_title, headings



