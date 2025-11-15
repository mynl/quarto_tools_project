# quarto_tools

Utilities for working with Quarto projects in Python:

* build compact TikZ tables of contents from `.qmd` files,
* generate trimmed BibTeX files containing only the references used in the project,
* audit Quarto cross-references (labels and refs) across the project.

The tools share one core philosophy: operate directly on `.qmd`, `_quarto.yml`, and `.bib` files using simple Python logic, without heavy external parsers. Everything is fast and transparent.

## Features

### Project discovery

* Understands Quarto projects through `_quarto.yml` / `_quarto.yaml`.
* Can operate on a single `.qmd`, a directory of `.qmd` files, or an explicit project YAML file.
* Supports glob-style file patterns (`-g/--pattern`) and explicit file lists (`-f/--file`).

### Table of Contents (TOC)

* Extracts headings from `.qmd` files, ignoring code blocks.
* Respects Quarto project ordering.
* Produces compact TikZ output suitable for LaTeX.
* Supports configurable column widths, wrapping, level limits, and omit-lists.

### BibTeX trimming

* Discovers BibTeX files from project YAML and front matter.
* Extracts only citation keys actually used in `.qmd` files.
* Parses BibTeX via a simple custom reader into a pandas DataFrame.
* Removes noisy fields such as `abstract`, `file`, or `annote`.
* Filters links to keep likely-official sources (DOIs, publisher URLs).
* Writes a compact `.bib` and optionally a CSV dump of the DataFrame.

### Cross-reference auditing (xrefs)

* Scans for Quarto labels (`{#fig-...}`, `{#sec-...}`) and chunk labels (`#| label: fig-...`).
* Scans for Quarto-style cross-references (`@fig-...`, `@sec-...`) while ignoring normal BibTeX citations.
* Tracks where each label is defined and where each ref is used.
* Reports duplicates, undefined references, unused labels, and prefix statistics.
* Provides CSV outputs for debugging.

## Installation

Development installation:

```cmd
py -m pip install -e .
```

This installs the package in editable mode so changes are reflected immediately.

## Command line usage

Using the installed console script:

```cmd
qt [COMMAND] ...
```

### TOC generation

```cmd
qt toc INPUT_PATH OUTPUT_FILE.tex [options]
```

`INPUT_PATH` may be:

* a Quarto project directory containing `_quarto.yml`,
* an individual `.qmd` file,
* a standalone project `_quarto.yml` file.

Useful options:

* `-g, --pattern`: glob patterns for selecting `.qmd` files,
* `-f, --file`: explicit `.qmd` files (may be given multiple times),
* `-c, --max-columns-per-row`: wrap threshold,
* `-w, --column-width`: TikZ column width,
* `-h, --section-max-height`: max subcolumn height,
* `-m, --chapter-min-height`: min chapter box height,
* `-v, --max-levels`: limit the heading depth,
* `-u/--up-level`: apply up-leveling logic,
* `-b, --balance-mode`: subcolumn packing strategy (`stable` or `ffd`),
* `-o, --omit`: titles to exclude,
* `-d/--debug`: annotate the TikZ for diagnostics.

### BibTeX trimming

```cmd
qt bibtex PROJECT_ROOT --bib-out trimmed.bib
```

Optional:

* `-d, --df-out path.csv`: write the internal DataFrame as CSV,
* `-w, --win-encoding cp1252`: write CSV with Windows encoding if needed.

This extracts only the keys cited in the project and writes a compact `.bib`.

### Cross-reference audit

```cmd
qt xrefs PROJECT_ROOT
```

Optional:

* `-w, --write-csv`: write defs/refs/duplicates/undefined/unused as CSV,
* `-o, --out-prefix`: prefix for CSV files,
* `-f, --fail-on-error`: exit with non-zero status if issues are detected.

The `xrefs` command prints:

* a summary table,
* lists of duplicate labels,
* undefined references.

When CSVs are enabled, all intermediate tables are written with the chosen prefix.

## Python API

These tools can also be used directly from Python.

### TOC

```python
from pathlib import Path
from quarto_tools.toc import QuartoToc

qt = QuartoToc(base_dir=Path("project"))
df = qt.make_df()
tikz = qt.to_tikz()

qt.write_tex(Path("toc.tex"), promote_chapter=-1)
```

### BibTeX trimming

```python
from pathlib import Path
from quarto_tools.bibtex import QuartoBibTex

qb = QuartoBibTex(base_dir=Path("project"))
df = qb.make_df()
qb.write_bib(Path("references-trimmed.bib"))
```

### Cross-references

```python
from pathlib import Path
from quarto_tools.xref import QuartoXRefs

xr = QuartoXRefs(base_dir=Path("project"))
defs_df, refs_df = xr.scan()
results = xr.validate()
```

Results include:

* duplicate_labels_df
* undefined_refs_df
* unused_defs_df
* prefix_stats_df
* summary_df

## Notes

* Line endings, code blocks, HTML comments, and Pandoc attributes are handled consistently.
* The cross-reference scanner uses shared prefix and suffix patterns so TOC, BibTeX, and xref tools interpret Quarto conventions the same way.
* All file paths stored in DataFrames are stored relative to `base_dir` to keep tables compact.

## Status

APIs are stable enough for daily use but may evolve as more functionality is added. Contributions and refinements are welcome.

 
