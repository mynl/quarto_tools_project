"""
Utilities for parsing fenced code blocks (e.g. ```{python}```) from QMD files.

This module is shared by QuartoTidy and QuartoPyTest. Existing classes in
quarto_tools do not depend on it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import re


@dataclass
class CodeBlock:
    """
    Representation of a fenced code block from a .qmd file.

    Attributes
    ----------
    file :
        The source .qmd file.
    block_index :
        1-based index of the block within the source file.
    lang :
        Language declared in the fence (e.g. "python").
    label :
        Optional #| label: value inside the block.
    caption :
        Optional #| ...-cap: caption text inside the block.
    code :
        The source code contained in the block.
    start_line :
        Optional starting line number of the code within the file (1-based).
    end_line :
        Optional ending line number of the code within the file (1-based).
    """
    file: Path
    block_index: int
    lang: str
    label: Optional[str]
    caption: Optional[str]
    code: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None


# Fenced block: ```{lang ...}\n...code...\n```
BLOCK_RE = re.compile(
    r"```{(?P<lang>[a-zA-Z0-9_-]+)[^}]*}\s*\n?(?P<code>.*?)```",
    re.DOTALL,
)

# Chunk annotations inside the block
LABEL_RE = re.compile(r"#\|\s*label:\s*(\S+)")
CAPTION_RE = re.compile(r"#\|\s*\S*?-cap:\s*['\"](.+?)['\"]")


def extract_code_blocks(
    text: str,
    file: Path,
    lang: Optional[str] = "python",
) -> list[CodeBlock]:
    """
    Extract fenced code blocks from a QMD string.

    Parameters
    ----------
    text :
        Full .qmd text.
    file :
        Path to the file (for metadata only).
    lang :
        If not None, only blocks with this language (case-insensitive) are
        returned. If None, all languages are returned.

    Returns
    -------
    list[CodeBlock]
        Parsed code block objects, in order.
    """
    blocks: list[CodeBlock] = []

    for i, match in enumerate(BLOCK_RE.finditer(text), start=1):
        block_lang = match.group("lang")
        if lang is not None and block_lang.lower() != lang.lower():
            continue

        code = match.group("code").strip("\n")

        # Compute line numbers for the code region (exclude fence line).
        code_start_idx = match.start("code")
        start_line = text[:code_start_idx].count("\n") + 1
        end_line = start_line + code.count("\n")

        # Extract optional label and caption from inside the block.
        label_match = LABEL_RE.search(code)
        caption_match = CAPTION_RE.search(code)

        label = label_match.group(1) if label_match else None
        caption = caption_match.group(1) if caption_match else None

        blocks.append(
            CodeBlock(
                file=file,
                block_index=i,
                lang=block_lang,
                label=label,
                caption=caption,
                code=code,
                start_line=start_line,
                end_line=end_line,
            )
        )

    return blocks
