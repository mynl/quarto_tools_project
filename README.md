# quarto_tools

Utilities for working with [Quarto](https://quarto.org) projects in Python.

The initial focus is on two tasks:

- Generating compact tables of contents (TOCs) for Quarto projects, including TikZ output suitable for LaTeX.
- Building trimmed BibTeX files that include only the references actually cited in your `.qmd` files, with noisy fields removed.

The package assumes a “standard” Quarto book or project structure, with a `_quarto.yml` / `_quarto.yaml` at the project root and content in `.qmd` files.

## Features

- Walk a Quarto project, respecting the project’s file ordering.
- Extract headings and labels from `.qmd` files, ignoring code blocks, to build a structured TOC.
- Read one or more BibTeX files into a pandas DataFrame without using external BibTeX libraries.
- Scan `.qmd` files for `@citekey` style citations and select only those entries from the BibTeX sources.
- Drop noisy BibTeX fields (for example, `abstract`, `file`, `annote`) to create a compact `.bib`.
- Optionally filter URLs to keep only “official” targets such as DOIs and publisher sites.

## Installation

From a local checkout:

```cmd
py -m pip install -e .
```

This installs quarto_tools in editable mode so you can iterate on the code.

## High-level usage

Typical usage patterns (APIs subject to change while things are experimental):

```python
from pathlib import Path

from quarto_tools.toc import QuartoToc
from quarto_tools.bibtex import QuartoBibTex

project_root = Path("path/to/quarto/project")

# Build a TOC DataFrame and generate TikZ
qt = QuartoToc(base_dir=project_root)
toc_df = qt.make_df()
tikz_code = qt.to_tikz()

# Build a compact BibTeX DataFrame and write a trimmed .bib
qb = QuartoBibTex(base_dir=project_root)
bib_df = qb.make_df()
qb.write_bib(project_root / "references-trimmed.bib")

```

APIs will be documented more fully once they stabilize.

## TODO

### toc

1. Option to number the first chapter
2. Better detection of the title in glob mode EG look at the reading or trees
3. Ordering of the files in glob mode 
