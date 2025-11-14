"""
quarto_tools: utilities for working with Quarto projects.

This package currently provides:

- QuartoToc: build structured tables of contents from .qmd files.
- QuartoBibTex: build trimmed BibTeX files containing only cited entries.
"""

from .toc import QuartoToc 
from .bibtex import QuartoBibTex

__all__ = ["QuartoToc", "QuartoBibTex"]

__version__ = "1.0.0"
