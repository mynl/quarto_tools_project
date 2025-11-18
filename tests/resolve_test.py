"""
Tests for resolve_quarto_context.

Covers:
1. input_path is dir containing _quarto.ya?ml
2. input_path is a qmd file
3. input_path is a yaml file
4. input_path is a non-qmd, non-yaml file (parent as base_dir)

Also checks:
- file_patterns always subset (never override)
- explicit_files always trump patterns/YAML; base_dir just says where to look
"""

from pathlib import Path

import pytest

from quarto_tools.utils import resolve_quarto_context


def _touch(path: Path) -> None:
    """
    Create an empty file at path, making parents as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_dir_with_quarto_yaml(tmp_path: Path) -> None:
    """
    Case 1: input_path is a dir containing _quarto.yml/_quarto.yaml.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    yaml_path = project_dir / "_quarto.yml"
    _touch(yaml_path)

    explicit_files: tuple[Path, ...] = ()
    file_patterns = ("posts/*.qmd",)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=project_dir,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml == yaml_path
    assert patterns == file_patterns
    assert final_explicit == explicit_files


def test_dir_without_quarto_yaml(tmp_path: Path) -> None:
    """
    Case 1b: input_path is a dir without YAML; generic directory case.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    explicit_files: tuple[Path, ...] = ()
    file_patterns = ("posts/*.qmd",)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=project_dir,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml is None
    assert patterns == file_patterns
    assert final_explicit == explicit_files


def test_single_qmd_file_without_explicit_files(tmp_path: Path) -> None:
    """
    Case 2: input_path is a .qmd file, no explicit_files.

    Expect:
    - base_dir = parent
    - project_yaml = None
    - patterns = ()
    - explicit_files = (that .qmd file,)
    """
    project_dir = tmp_path / "pmir-test"
    posts_dir = project_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    qmd_path = posts_dir / "030-bullets.qmd"
    _touch(qmd_path)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=qmd_path,
        explicit_files=(),
        file_patterns=("ignored/*.qmd",),
    )

    assert base_dir == posts_dir
    assert project_yaml is None
    assert patterns == ()
    assert final_explicit == (qmd_path,)


def test_single_qmd_file_with_explicit_files(tmp_path: Path) -> None:
    """
    Case 2b: input_path is a .qmd file, explicit_files already given.

    Expect:
    - explicit_files unchanged
    - patterns ignored (still ())
    """
    project_dir = tmp_path / "pmir-test"
    posts_dir = project_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    qmd_path = posts_dir / "030-bullets.qmd"
    other_path = posts_dir / "040-other.qmd"
    _touch(qmd_path)
    _touch(other_path)

    explicit_files = (other_path,)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=qmd_path,
        explicit_files=explicit_files,
        file_patterns=("ignored/*.qmd",),
    )

    assert base_dir == posts_dir
    assert project_yaml is None
    assert patterns == ()
    assert final_explicit == explicit_files


def test_yaml_file_as_project_root(tmp_path: Path) -> None:
    """
    Case 3: input_path is an explicit _quarto.yml/_quarto.yaml file.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    yaml_path = project_dir / "_quarto.yml"
    _touch(yaml_path)

    explicit_files: tuple[Path, ...] = ()
    file_patterns = ("posts/*.qmd",)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=yaml_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml == yaml_path
    assert patterns == file_patterns
    assert final_explicit == explicit_files


def test_non_qmd_non_yaml_file_parent_as_base_dir(tmp_path: Path) -> None:
    """
    Case 4: input_path is some other file; parent used as base_dir.

    This is a graceful fallback: treat the parent directory as the project
    root, with no YAML, and let patterns/explicit_files behave as usual.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    notes_path = project_dir / "notes.txt"
    _touch(notes_path)

    explicit_files: tuple[Path, ...] = ()
    file_patterns = ("posts/*.qmd",)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=notes_path,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml is None
    assert patterns == file_patterns
    assert final_explicit == explicit_files


def test_explicit_files_always_trump(tmp_path: Path) -> None:
    """
    In all cases, non-empty explicit_files take precedence over patterns/YAML.

    We test by passing a directory with YAML plus explicit_files and making
    sure explicit_files come through unchanged and patterns are not altered.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    yaml_path = project_dir / "_quarto.yml"
    _touch(yaml_path)

    posts_dir = project_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    q1 = posts_dir / "010-intro.qmd"
    q2 = posts_dir / "020-main.qmd"
    _touch(q1)
    _touch(q2)

    explicit_files = (q1, q2)
    file_patterns = ("posts/*.qmd",)

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=project_dir,
        explicit_files=explicit_files,
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml == yaml_path
    assert patterns == file_patterns
    assert final_explicit == explicit_files


def test_file_patterns_never_override(tmp_path: Path) -> None:
    """
    file_patterns always *subset* discovery; resolve_quarto_context should
    never rewrite or ignore non-empty patterns (except for the single-qmd
    case where we force single-file context).

    Here we use a project dir with YAML and ensure patterns pass through.
    """
    project_dir = tmp_path / "pmir-test"
    project_dir.mkdir()

    yaml_path = project_dir / "_quarto.yml"
    _touch(yaml_path)

    file_patterns = ("posts/*.qmd", "other/*.qmd")

    base_dir, project_yaml, patterns, final_explicit = resolve_quarto_context(
        input_path=project_dir,
        explicit_files=(),
        file_patterns=file_patterns,
    )

    assert base_dir == project_dir
    assert project_yaml == yaml_path
    assert patterns == file_patterns
    assert final_explicit == ()
