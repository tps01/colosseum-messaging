"""Artifact paths stay inside the active run directory."""

from __future__ import annotations

from typing import TYPE_CHECKING

import colosseum.context as context_module
import pytest
from colosseum_messaging._paths import resolve_artifact_path
from colosseum_messaging.ssh._file_select import map_remote_get_paths

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def run_dir(tmp_path: Path):
    previous = context_module._ACTIVE_CONTEXT
    root = tmp_path / "run"
    root.mkdir()
    ctx = context_module.init_context(test_case_name="artifact_paths")
    ctx.output_dir = root
    ctx.runtime_ready = True
    try:
        yield root
    finally:
        context_module._ACTIVE_CONTEXT = previous


def test_sibling_prefix_cannot_escape_run_directory(run_dir: Path) -> None:
    outside = run_dir.parent / "run-other" / "evidence.txt"
    with pytest.raises(ValueError, match="output directory"):
        resolve_artifact_path("../run-other/evidence.txt")
    assert not outside.exists()


def test_parent_traversal_cannot_escape_run_directory(run_dir: Path) -> None:
    outside = run_dir.parent / "outside.txt"
    with pytest.raises(ValueError, match="output directory"):
        resolve_artifact_path("../outside.txt")
    assert not outside.exists()


def test_nested_artifact_stays_inside_run_directory(run_dir: Path) -> None:
    path = resolve_artifact_path("nested/evidence.txt")
    assert path.is_relative_to(run_dir.resolve())
    assert path.parent.is_dir()
    assert path.name == "evidence.txt"


def test_absolute_path_inside_run_directory_is_accepted(run_dir: Path) -> None:
    inside = (run_dir / "abs" / "ok.txt").resolve()
    path = resolve_artifact_path(str(inside))
    assert path == inside
    assert path.parent.is_dir()


def test_absolute_path_outside_run_directory_is_rejected(run_dir: Path) -> None:
    outside = (run_dir.parent / "elsewhere" / "nope.txt").resolve()
    with pytest.raises(ValueError, match="output directory"):
        resolve_artifact_path(str(outside))


def test_download_destination_is_rechecked(run_dir: Path) -> None:
    mapped = map_remote_get_paths(
        ["/var/log/app/a.txt"],
        "/var/log/*.txt",
        "downloads",
        resolve_local=resolve_artifact_path,
    )
    destination = mapped[0][1]
    assert destination.is_relative_to(run_dir.resolve())
    assert destination.name == "a.txt"
    assert destination.parent.is_dir()

    outside = run_dir.parent / "run-other" / "evidence.txt"
    with pytest.raises(ValueError, match="output directory"):
        map_remote_get_paths(
            ["/var/log/../../run-other/evidence.txt"],
            "/var/log/*.txt",
            "downloads",
            resolve_local=resolve_artifact_path,
        )
    assert not outside.exists()
