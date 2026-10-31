#!/usr/bin/env python3
"""Resolve which colosseum-core git ref plugins should ``--also-build``.

On a version tag publish (``refs/tags/v*``), pick the newest published core
release tag that satisfies this package's ``colosseum-core`` requirement.
Otherwise print ``develop`` (workflow_dispatch / branch builds).

Usage (from a plugin repo root)::

  python scripts/ci/resolve_core_ref.py
  CORE_REF=$(python scripts/ci/resolve_core_ref.py)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

try:
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging ships with pip
    SpecifierSet = None  # type: ignore[misc, assignment]
    Version = None  # type: ignore[misc, assignment]
    InvalidVersion = Exception  # type: ignore[misc, assignment]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_core_specifier(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(
        r'"colosseum-core\s*([^"]+)"',
        text,
    )
    if not match:
        # Also allow bare name with no version (treat as any).
        if re.search(r'"colosseum-core"', text):
            return ">=0"
        raise SystemExit(f"No colosseum-core dependency found in {pyproject}")
    return match.group(1).strip()


def _is_version_tag_ref(ref: str) -> bool:
    return bool(re.fullmatch(r"refs/tags/v\d+\.\d+\.\d+", ref))


def _list_core_tags() -> list[str]:
    proc = subprocess.run(
        [
            "gh",
            "release",
            "list",
            "-R",
            "tps01/colosseum-core",
            "--limit",
            "100",
            "--json",
            "tagName",
            "--jq",
            ".[].tagName",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "gh release list failed for tps01/colosseum-core:\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}",
        )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _newest_satisfying_tag(tags: list[str], specifier: str) -> str:
    if SpecifierSet is None or Version is None:
        raise SystemExit("packaging is required (install pip/packaging)")
    spec = SpecifierSet(specifier)
    candidates: list[tuple[Version, str]] = []
    for tag in tags:
        if not tag.startswith("v"):
            continue
        ver_text = tag[1:]
        try:
            ver = Version(ver_text)
        except InvalidVersion:
            continue
        if ver in spec:
            candidates.append((ver, tag))
    if not candidates:
        raise SystemExit(
            f"No tps01/colosseum-core release tag satisfies {specifier!r} "
            f"(saw {len(tags)} tags)",
        )
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def resolve_core_ref(
    *,
    github_ref: str,
    pyproject: Path,
    tags: list[str] | None = None,
) -> str:
    """Return core checkout ref for the current workflow context."""
    if not _is_version_tag_ref(github_ref):
        return "develop"
    specifier = _read_core_specifier(pyproject)
    tag_list = tags if tags is not None else _list_core_tags()
    return _newest_satisfying_tag(tag_list, specifier)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github-ref",
        default=os.environ.get("GITHUB_REF", ""),
        help="Git ref (default: $GITHUB_REF)",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=None,
        help="Plugin pyproject.toml (default: <repo>/pyproject.toml)",
    )
    args = parser.parse_args(argv)
    root = _repo_root()
    pyproject = (args.pyproject or (root / "pyproject.toml")).resolve()
    if not pyproject.is_file():
        raise SystemExit(f"Missing pyproject: {pyproject}")
    print(resolve_core_ref(github_ref=args.github_ref, pyproject=pyproject))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
