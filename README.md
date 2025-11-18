# quarto_tools

Utilities for working with Quarto projects in Python:

* build compact TikZ tables of contents from `.qmd` files,
* generate trimmed BibTeX files containing only the references used in the project,
* audit Quarto cross-references (labels and refs) across the project,
* tidy and normalize `.qmd` files (flatten includes, clean paragraphs, remove comments),
* extract, syntax-check, and execute Python blocks embedded in `.qmd` files.
* consolidate a book project into a single file.

The tools share one core philosophy: operate directly on `.qmd`, `_quarto.yml`, and `.bib` files using simple Python logic, without heavy external parsers. Everything is fast and transparent.

All commands share a unified project-discovery system.
Each command accepts an `INPUT_PATH` which may be:

* a directory,
* a single `.qmd`,
* a `_quarto.yml` or `_quarto.yaml` file,

and may be refined with:

* `-f FILE` one or more explicit `.qmd` files,
* `-g PATTERN` one or more ripgrep-style glob patterns.

Under the hood this is implemented in `utils.resolve_quarto_context`, which ensures all commands behave consistently.

---

## Features

### Project discovery

* Understands Quarto projects via `_quarto.yml` / `_quarto.yaml`.
* Can operate on a directory of `.qmd` files, a single `.qmd`, or an explicit project YAML file.
* Supports ripgrep-style file patterns (`-g/--pattern`) and explicit file lists (`-f/--file`).
* `explicit_files` always override patterns and YAML.
* `.qmd` input forces single-file mode unless explicit files are given.

### Table of Contents (TOC)

* Extracts headings from `.qmd` files, ignoring code blocks.
* Respects Quarto project ordering from YAML.
* Produces compact TikZ output suitable for LaTeX.
* Configurable column widths, wrapping logic, level limits, and omit-lists.
* Debug mode for visualizing layout and diagnostics.

### BibTeX trimming

* Discovers BibTeX files from project YAML and front matter.
* Extracts only citation keys actually used in `.qmd` files.
* Parses BibTeX into a clean pandas DataFrame.
* Removes noisy or unhelpful fields (e.g., `abstract`, `file`, `annote`).
* Prefers useful links such as DOIs and publisher URLs.
* Can write tidy `.bib` files and optional CSVs.

### Cross-reference auditing (xrefs)

* Scans for Quarto labels (`{#fig-...}`, `{#sec-...}`) and chunk labels (`#| label: fig-...`).
* Scans for Quarto-style cross-references (`@fig-...`, `@sec-...`) while ignoring BibTeX citations.
* Reports duplicates, undefined references, unused labels, and useful prefix statistics.
* `--write-csv` mode dumps all tables for debugging.

### Tidy

The `tidy` command group provides three functions:

**1. Flatten**
Inline all `{{< include >}}` blocks:

```
qt tidy flatten-file input.qmd output.qmd
```

Options include recursive flattening and include-markers.

**2. Format / normalize**
Clean and rewrite `.qmd` files:

* normalize paragraph spacing,
* maintain clean code-block boundaries,
* remove or keep HTML comments,
* wrap paragraphs if desired,
* write output either in-place or to a separate directory.

**3. Report**
Runs:

* cross-reference audit,
* BibTeX audit,
* Python-block enumeration,

and prints a unified report for an entire project.

### Python code-block testing (qpytest)

The `qpytest` group operates on fenced Python blocks discovered via `blocks.py`.

Capabilities:

* **collect** — list python blocks with labels and captions,
* **extract** — generate one `.py` file per `.qmd` capturing all python blocks,
* **run** — syntax-check or execute each block using IPython and matplotlib Agg,
* **run-parallel** — run each chapter in a separate subprocess for major speedups.

Outputs include structured summaries and optional `.output`, `.stderr`, and `.error` files next to each extracted script.

### Project consolidation (consolidate)

* Converts an entire Quarto book or project into a single `.qmd` file.
* Uses the project’s `_quarto.yml` to discover chapter order.
* Inlines all `{{< include >}}` directives recursively, producing a fully expanded document.
* Strips per-file YAML front matter by default; the `--comment-front-matter` flag preserves it as commented blocks.
* Converts each file’s `title:` into a chapter heading at the chosen level.
* Produces a clean, linear document suitable for debugging, diffing, archiving, or standalone rendering.

### Interactive shell (uber)

* `qt uber` starts an interactive prompt for running multiple `qt` commands
  without reloading the library each time.
* Provides fuzzy autocompletion for all subcommands, plus navigation helpers
  (`cd`, `pwd`, `dir`, `cls`, `e`, `ex`, `ev`).
* Useful for exploratory work, repeated TOC generation, quick tidy / xref cycles,
  or anything where reload time becomes distracting.
* The first argument may be an initial command to run before dropping
  into the prompt.
* Use `-p` to customize the prompt label and `-d` for debug output.

Example:

```python
qt uber
# or
qt uber -p "qt-tools"
```

Exit with `q`, `x`, `quit`, or `exit`.


### Scripted execution (script)

* `qt script my-commands.txt` runs a sequence of commands in a single process,
  amortizing import time just like `uber`.
* Each non-empty, non-comment line is treated as a `qt` command.
* Lines ending with `\` are continued onto the next line (Python-style).
* Errors in individual commands do not abort the script unless the underlying
  command does.

Example `my-commands.txt`:

```python
# Build README TOC
toc . toc/README.tex
-f README.md
# Trim BibTeX
bibtex . --write
```

Run with:

```
qt script my-commands.txt
```


## Installation

Development installation:

```bash
py -m pip install -e .
```

This installs the package in editable mode so changes are reflected immediately.

---

## Command line usage

Using the installed console script:

```bash
qt [COMMAND] ...
```

---

### TOC generation

```bash
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
* `-v, --max-levels`: limit heading depth,
* `-u, --up-level`: apply up-leveling logic,
* `-b, --balance-mode`: subcolumn packing (`stable` or `ffd`),
* `-o, --omit`: titles to exclude,
* `-d, --debug`: annotate TikZ for diagnostics.

---

### BibTeX trimming

```bash
qt bibtex INPUT_PATH
```

Optional:

* `-w, --write-csv`: dump internal citation/tags tables,
* `-o, --out-prefix`: filename prefix for CSV output,
* `--fail-on-error`: treat missing/unused entries as an error.

---

### Cross-reference audit

```bash
qt xrefs INPUT_PATH
```

Optional:

* `-w, --write-csv`: write full tables,
* `-o, --out-prefix`: prefix for CSV files,
* `-f, --fail-on-error`: exit with non-zero status on issues.

Reports:

* duplicate labels,
* undefined references,
* unused labels.

---

### Tidy

#### Flatten a file

```bash
qt tidy flatten-file input.qmd output.qmd
```

#### Format files

```bash
qt tidy format INPUT_PATH [options]
```

Useful options:

* `--in-place` or `-o DIR`: write normalized output,
* `--remove-comments`: drop HTML comments outside code blocks,
* `--wrap-width N`: optional text wrapping.

#### Report

```bash
qt tidy report INPUT_PATH
```

Runs xrefs, bibtex checks, and Python-block enumeration.

---

### Testing Python code blocks

The `qpytest` group uses the shared parser in `blocks.py`.

#### Collect blocks

```bash
qt qpytest collect INPUT_PATH
```

#### Extract to `.py`

```bash
qt qpytest extract INPUT_PATH OUT_DIR
```

Each `.qmd` becomes one `.py` script containing all code blocks.

#### Syntax-check / execute

```bash
qt qpytest run INPUT_PATH --mode syntax
qt qpytest run INPUT_PATH --mode exec
```

Execution uses an isolated IPython shell and matplotlib Agg.

#### Parallel execution

```bash
qt qpytest run-parallel INPUT_PATH -n 4
```

Runs each chapter’s `.py` script in its own subprocess; useful for large books.

---

## Python API

These tools can also be used directly from Python.

### TOC

```python
from pathlib import Path
from quarto_tools.toc import QuartoToc

toc = QuartoToc(base_dir=Path("project"))
df = toc.make_df()
tikz = toc.to_tikz()
toc.write_tex(Path("toc.tex"))
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

### Tidy

```python
from quarto_tools.tidy import QuartoTidy

t = QuartoTidy(base_dir=Path("project"))
t.flatten_file("input.qmd", "output.qmd")
t.format_all(in_place=True)
```

### qpytest

```python
from quarto_tools.pytest_qmd import QuartoPyTest

qp = QuartoPyTest(base_dir=Path("project"))
blocks = qp.list_blocks()
qp.extract(Path("out_dir"))
qp.run(mode="syntax")
```

---

## Notes

* Line endings, code blocks, HTML comments, and Pandoc attributes are handled consistently.
* All commands share the same INPUT_PATH resolver, ensuring predictable behavior.
* Code blocks are parsed using a single central lexer in `blocks.py`.
* Python execution uses isolated IPython shells for correctness and reproducibility.
* All DataFrame outputs use paths relative to `base_dir` for compactness.

---

## Status

APIs are stable for daily use but continue to evolve as new Quarto features and workflows are supported.

---

If you'd like, I can also produce:

* a shorter “quickstart” version,
* a developer-only README for maintainers,
* or a manpage-style help summary matching the CLI.

