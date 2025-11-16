"""
Python extraction and testing for Quarto .qmd files.

This module is independent of tidy/xref/bibtex functionality. It provides:

- collect_blocks: enumerate python code blocks
- extract: write them to .py files (one per .qmd)
- run: syntax-test or execute blocks, optionally in parallel via subprocesses

The CLI layer should handle user interaction and pretty printing; this module
focuses on data and results.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncio
import shlex

import matplotlib
import pandas as pd
from IPython.core.interactiveshell import InteractiveShell

from .blocks import CodeBlock, extract_code_blocks
from .utils import discover_quarto_sources


@dataclass
class QuartoPyTest:
    """
    Extract and test Python code blocks from Quarto .qmd files.

    Parameters
    ----------
    base_dir :
        Root directory for the project.
    project_yaml :
        Optional path to project-level _quarto.yml / _quarto.yaml.
    file_patterns :
        Glob patterns for source discovery (ripgrep -g style).
    explicit_files :
        Explicitly provided .qmd files. If non-empty, take precedence over
        patterns and project yaml.
    encoding :
        Text encoding for reading .qmd files.
    """
    base_dir: Path
    project_yaml: Path | None = None
    file_patterns: tuple[str, ...] = ()
    explicit_files: tuple[Path, ...] = ()
    encoding: str = "utf-8"

    _sources: list[Path] | None = field(default=None, init=False, repr=False)

    # ------------------------
    # Internal helpers
    # ------------------------

    def _discover_sources(self) -> list[Path]:
        """
        Discover .qmd files using the shared project-discovery logic.

        Returns
        -------
        list[Path]
            Source files in project order.
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

    def _collect_block_objects(self) -> list[CodeBlock]:
        """
        Collect CodeBlock objects for all python code blocks in the project.

        Returns
        -------
        list[CodeBlock]
        """
        blocks: list[CodeBlock] = []
        for src in self._discover_sources():
            text = src.read_text(encoding=self.encoding)
            file_blocks = extract_code_blocks(text, src, lang="python")
            blocks.extend(file_blocks)
        return blocks

    # ------------------------
    # Feature: collect
    # ------------------------

    def collect_blocks(self) -> pd.DataFrame:
        """
        Return a DataFrame of all Python code blocks across the project.

        Columns
        -------
        file :
            Path to the .qmd file, relative to base_dir.
        block_index :
            1-based index of the block within the file.
        lang :
            Language in the fence (always "python" here).
        label :
            Optional #| label: value.
        caption :
            Optional #| ...-cap: text.
        start_line :
            Starting line number of the code in the file (1-based).
        end_line :
            Ending line number of the code in the file (1-based).
        code :
            The block source code.
        """
        blocks = self._collect_block_objects()
        if not blocks:
            return pd.DataFrame(
                columns=[
                    "file",
                    "block_index",
                    "lang",
                    "label",
                    "caption",
                    "start_line",
                    "end_line",
                    "code",
                ]
            )

        records: list[dict[str, Any]] = []
        for block in blocks:
            records.append(
                {
                    "file": block.file.relative_to(self.base_dir),
                    "block_index": block.block_index,
                    "lang": block.lang,
                    "label": block.label,
                    "caption": block.caption,
                    "start_line": block.start_line,
                    "end_line": block.end_line,
                    "code": block.code,
                }
            )

        return pd.DataFrame.from_records(records)

    # ------------------------
    # Feature: extract
    # ------------------------

    def extract(self, output_dir: Path) -> pd.DataFrame:
        """
        Extract Python blocks into .py files, one per source .qmd file.

        For each .qmd file containing at least one python block, a .py file
        is written under output_dir with a mirrored directory structure.
        The .py file name is the same as the .qmd stem, with suffix .py.

        Each block is separated by a comment header indicating its index,
        label, and caption where available.

        Parameters
        ----------
        output_dir :
            Destination directory for the extracted .py files.

        Returns
        -------
        pandas.DataFrame
            Summary with columns:

            - file: original .qmd path, relative to base_dir
            - py_file: generated .py path, relative to output_dir
            - blocks: number of blocks written
        """
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        blocks = self._collect_block_objects()
        if not blocks:
            return pd.DataFrame(
                columns=["file", "py_file", "blocks"],
            )

        by_file: dict[Path, list[CodeBlock]] = {}
        for block in blocks:
            by_file.setdefault(block.file, []).append(block)

        records: list[dict[str, Any]] = []

        for src, file_blocks in by_file.items():
            file_blocks.sort(key=lambda b: b.block_index)

            rel = src.relative_to(self.base_dir)
            py_path = (output_dir / rel).with_suffix(".py")
            py_path.parent.mkdir(parents=True, exist_ok=True)

            lines: list[str] = []
            for block in file_blocks:
                header_parts: list[str] = [f"# === Block {block.block_index}"]
                if block.label:
                    header_parts.append(f"label={block.label}")
                if block.caption:
                    header_parts.append(f"caption={block.caption!r}")
                header = " ".join(header_parts)
                lines.append(header)
                lines.append(block.code)
                lines.append("")

            text = "\n".join(lines)
            if text and not text.endswith("\n"):
                text = text + "\n"

            py_path.write_text(text, encoding=self.encoding)

            records.append(
                {
                    "file": rel,
                    "py_file": py_path.relative_to(output_dir),
                    "blocks": len(file_blocks),
                }
            )

        return pd.DataFrame.from_records(records)

    # ------------------------
    # Feature: run (single-process)
    # ------------------------

    def run(
        self,
        mode: str = "syntax",
    ) -> pd.DataFrame:
        """
        Test Python code blocks in a single process.

        Parameters
        ----------
        mode :
            Either "syntax" or "exec".

            - "syntax": only compile each block with compile(..., 'exec').
              No code is executed; this checks for SyntaxError only.
            - "exec": execute each block in an IPython InteractiveShell
              instance with matplotlib using the "Agg" backend.

        Returns
        -------
        pandas.DataFrame
            One row per block with columns:

            - file: .qmd path relative to base_dir
            - block_index
            - label
            - mode
            - ok: True if compile/exec succeeded, False otherwise
            - error_type: exception class name (or None)
            - error_message: string message (or None)
            - lineno: error line number within the block, if available
            - col_offset: error column offset, if available
        """
        mode = mode.lower()
        if mode not in {"syntax", "exec"}:
            msg = "mode must be 'syntax' or 'exec'"
            raise ValueError(msg)

        blocks = self._collect_block_objects()
        records: list[dict[str, Any]] = []

        shell: InteractiveShell | None = None
        if mode == "exec":
            matplotlib.use("Agg")
            shell = InteractiveShell.instance()

        for block in blocks:
            rel = block.file.relative_to(self.base_dir)
            ok = False
            error_type: str | None = None
            error_message: str | None = None
            lineno: int | None = None
            col_offset: int | None = None

            if mode == "syntax":
                try:
                    compile(block.code, str(block.file), "exec")
                    ok = True
                except SyntaxError as exc:
                    error_type = type(exc).__name__
                    error_message = str(exc)
                    lineno = exc.lineno
                    col_offset = exc.offset
                except Exception as exc:
                    error_type = type(exc).__name__
                    error_message = str(exc)
            else:
                try:
                    assert shell is not None
                    result = shell.run_cell(block.code, store_history=False)
                    ok = bool(result.success)
                    if not ok and result.error_in_exec is not None:
                        exc = result.error_in_exec
                        error_type = type(exc).__name__
                        error_message = str(exc)
                        if hasattr(exc, "lineno"):
                            lineno = getattr(exc, "lineno")
                        if hasattr(exc, "offset"):
                            col_offset = getattr(exc, "offset")
                except Exception as exc:
                    error_type = type(exc).__name__
                    error_message = str(exc)

            records.append(
                {
                    "file": rel,
                    "block_index": block.block_index,
                    "label": block.label,
                    "mode": mode,
                    "ok": ok,
                    "error_type": error_type,
                    "error_message": error_message,
                    "lineno": lineno,
                    "col_offset": col_offset,
                }
            )

        if not records:
            return pd.DataFrame(
                columns=[
                    "file",
                    "block_index",
                    "label",
                    "mode",
                    "ok",
                    "error_type",
                    "error_message",
                    "lineno",
                    "col_offset",
                ]
            )

        return pd.DataFrame.from_records(records)

    # ------------------------
    # Feature: run in parallel (per chapter)
    # ------------------------

    async def _run_script_worker(
        self,
        name: str,
        queue: "asyncio.Queue[Path]",
        results: dict[Path, dict[str, Any]],
    ) -> None:
        """
        Async worker: run ipython script.py for queued scripts.

        Results are stored in the shared 'results' dict keyed by script path.
        """
        while True:
            script: Path = await queue.get()
            try:
                cmd = f"ipython {script}"
                args = shlex.split(cmd, posix=False)

                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await proc.communicate()
                rc = proc.returncode

                so = stdout.decode("utf-8", errors="replace") if stdout else ""
                se = stderr.decode("utf-8", errors="replace") if stderr else ""

                # Write outputs next to the script.
                if so:
                    script.with_suffix(".output").write_text(so, encoding="utf-8")
                if se:
                    script.with_suffix(".stderr").write_text(se, encoding="utf-8")

                # Optional .error file if non-zero return code.
                if rc != 0:
                    err_text = se or so
                    if err_text:
                        script.with_suffix(".error").write_text(
                            err_text, encoding="utf-8"
                        )

                results[script] = {
                    "returncode": rc,
                }
            finally:
                queue.task_done()

    async def _run_scripts_parallel(
        self,
        scripts: list[Path],
        n_workers: int,
    ) -> dict[Path, dict[str, Any]]:
        """
        Run scripts in parallel using asyncio subprocesses.

        Parameters
        ----------
        scripts :
            List of script paths to run with ipython.
        n_workers :
            Number of concurrent workers.

        Returns
        -------
        dict
            Mapping script path -> result dict (currently only 'returncode').
        """
        queue: asyncio.Queue[Path] = asyncio.Queue()
        for script in scripts:
            queue.put_nowait(script)

        results: dict[Path, dict[str, Any]] = {}

        tasks: list[asyncio.Task[None]] = []
        for i in range(n_workers):
            task = asyncio.create_task(
                self._run_script_worker(f"worker-{i}", queue, results)
            )
            tasks.append(task)

        await queue.join()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        return results

    def run_parallel(
        self,
        output_dir: Path | None = None,
        n_workers: int = 4,
    ) -> pd.DataFrame:
        """
        Execute chapters in parallel as independent scripts.

        This mode:
        - extracts one .py per .qmd with python blocks,
        - runs `ipython chapter.py` in parallel,
        - writes .output/.stderr/.error files per chapter,
        - maps the chapter result back to all its blocks.

        It does NOT tell you which specific block failed, only that the
        chapter script as a whole succeeded or failed.

        Parameters
        ----------
        output_dir :
            Directory to write the extracted .py scripts.
            If None, use base_dir / ".qpytest".
        n_workers :
            Number of concurrent workers.

        Returns
        -------
        pandas.DataFrame
            One row per block with columns:

            - file: .qmd path relative to base_dir
            - block_index
            - label
            - mode: "exec-parallel"
            - ok: True if the chapter script exit code was 0
            - error_type: None or "SubprocessError"
            - error_message: message including the return code
            - lineno, col_offset: always None (no block-level info here)
        """
        if output_dir is None:
            output_dir = (self.base_dir / ".qpytest").resolve()
        else:
            output_dir = output_dir.resolve()

        extract_df = self.extract(output_dir=output_dir)
        if extract_df.empty:
            return pd.DataFrame(
                columns=[
                    "file",
                    "block_index",
                    "label",
                    "mode",
                    "ok",
                    "error_type",
                    "error_message",
                    "lineno",
                    "col_offset",
                ]
            )

        scripts: list[Path] = []
        qmd_for_script: dict[Path, Path] = {}

        for _, row in extract_df.iterrows():
            rel_qmd: Path = row["file"]
            rel_py: Path = row["py_file"]
            script_path = output_dir / rel_py
            scripts.append(script_path)
            qmd_for_script[script_path] = (self.base_dir / rel_qmd).resolve()

        results = asyncio.run(self._run_scripts_parallel(scripts, n_workers=n_workers))

        # Map from qmd absolute path -> returncode
        rc_by_qmd: dict[Path, int] = {}
        for script_path, res in results.items():
            qmd_path = qmd_for_script[script_path]
            rc_by_qmd[qmd_path] = res.get("returncode", 1)

        blocks = self._collect_block_objects()
        records: list[dict[str, Any]] = []

        for block in blocks:
            rel = block.file.relative_to(self.base_dir)
            rc = rc_by_qmd.get(block.file, 0)
            ok = rc == 0
            error_type: str | None = None
            error_message: str | None = None
            if not ok:
                error_type = "SubprocessError"
                error_message = f"ipython exited with code {rc} for chapter"

            records.append(
                {
                    "file": rel,
                    "block_index": block.block_index,
                    "label": block.label,
                    "mode": "exec-parallel",
                    "ok": ok,
                    "error_type": error_type,
                    "error_message": error_message,
                    "lineno": None,
                    "col_offset": None,
                }
            )

        return pd.DataFrame.from_records(records)
