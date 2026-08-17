#!/usr/bin/env python3
"""Verify a release tag matches pyproject.toml version (CI-agnostic).

  python scripts/ci/verify_release_tag.py --tag v0.15.2
  python scripts/ci/verify_release_tag.py --tag 0.15.2

If --tag is omitted, uses env RELEASE_TAG, then GITHUB_REF_NAME.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_version(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit(f"Could not read version from {pyproject}")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None, help="Release tag (with or without v)")
    args = parser.parse_args(argv)

    tag = args.tag or os.environ.get("RELEASE_TAG") or os.environ.get("GITHUB_REF_NAME")
    if not tag:
        raise SystemExit("Pass --tag or set RELEASE_TAG / GITHUB_REF_NAME")

    expected = tag[1:] if tag.startswith("v") else tag
    actual = _project_version(_repo_root() / "pyproject.toml")
    print(f"Tag version: {expected}")
    print(f"Package version: {actual}")
    if expected != actual:
        raise SystemExit(f"Tag {tag!r} does not match project version {actual!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
