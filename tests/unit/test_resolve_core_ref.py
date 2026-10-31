"""Tests for scripts/ci/resolve_core_ref.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci" / "resolve_core_ref.py"


def _load():
    spec = importlib.util.spec_from_file_location("resolve_core_ref", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_non_tag_ref_returns_develop(tmp_path: Path) -> None:
    mod = _load()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        'dependencies = ["colosseum-core>=0.17.8,<0.18"]\n',
        encoding="utf-8",
    )
    assert (
        mod.resolve_core_ref(
            github_ref="refs/heads/develop",
            pyproject=pyproject,
            tags=["v0.17.13"],
        )
        == "develop"
    )


def test_tag_ref_picks_newest_satisfying(tmp_path: Path) -> None:
    mod = _load()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        'dependencies = ["colosseum-core>=0.17.8,<0.18"]\n',
        encoding="utf-8",
    )
    assert (
        mod.resolve_core_ref(
            github_ref="refs/tags/v0.7.2",
            pyproject=pyproject,
            tags=["v0.17.1", "v0.17.8", "v0.17.13", "v0.18.0"],
        )
        == "v0.17.13"
    )


def test_tag_ref_errors_when_none_satisfy(tmp_path: Path) -> None:
    mod = _load()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        'dependencies = ["colosseum-core>=0.17.8,<0.18"]\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="No tps01/colosseum-core"):
        mod.resolve_core_ref(
            github_ref="refs/tags/v0.7.2",
            pyproject=pyproject,
            tags=["v0.16.0", "v0.18.0"],
        )
