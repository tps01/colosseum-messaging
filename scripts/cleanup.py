#!/usr/bin/env python3
"""
Remove Colosseum build artifacts and temporary files from the repository tree.

Aligned with .gitignore (includes ``*.egg-info/``, ``.deps/``, and local venvs).
Does not delete source, docs, or local secrets (.env).

By default removes top-level ``.venv`` / ``.venv-*`` / ``venv`` / ``.deps`` directories.
Pass ``--keep-venvs`` to leave those environments and only scrub cache files inside them.

Usage:
  python scripts/cleanup.py --dry-run
  python scripts/cleanup.py
  python scripts/cleanup.py --keep-venvs
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

# Top-level directories under repo root to remove entirely.
ROOT_DIRS = (
    "outputs",
    "build",
    "dist",
    "develop-eggs",
    "downloads",
    "eggs",
    ".eggs",
    "lib",
    "lib64",
    "parts",
    "sdist",
    "var",
    "wheels",
    "share/python-wheels",
    "pip-wheel-metadata",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".hypothesis",
    ".deps",
)

# Top-level virtualenv directory names (also ``.venv-*`` / ``venv-*`` prefixes).
VENV_DIR_NAMES = frozenset({".venv", "venv", "ENV", "env"})


def _is_venv_top_level(name: str) -> bool:
    if name in VENV_DIR_NAMES:
        return True
    return name.startswith(".venv-") or name.startswith("venv-")


def _iter_venv_top_level_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for name in VENV_DIR_NAMES:
        path = root / name
        if path.is_dir():
            dirs.append(path)
    for child in root.iterdir():
        if child.is_dir() and _is_venv_top_level(child.name) and child.name not in VENV_DIR_NAMES:
            dirs.append(child)
    return dirs


# Directory names removed anywhere in the tree.
WALK_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}

# Safe generated artifacts to remove inside virtual environments when the venv itself is kept.
VENV_ARTIFACT_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
}
VENV_ARTIFACT_FILE_GLOBS = ("*.pyc", "*.pyo", "*$py.class")

# File globs removed anywhere in the tree.
WALK_FILE_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*$py.class",
    "*.so",
    ".coverage",
    ".coverage.*",
    ".DS_Store",
    "Thumbs.db",
    "Desktop.ini",
    "*.swp",
    "*.swo",
    "*~",
    "MANIFEST",
    "*.egg",
    "pip-log.txt",
)

# Directory globs anywhere in the tree (e.g. *.egg-info).
WALK_DIR_GLOBS = ("*.egg-info",)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _is_under_venv(root: Path, path: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return bool(rel_parts) and _is_venv_top_level(rel_parts[0])


def _collect_venv_artifacts(root: Path) -> list[Path]:
    targets: list[Path] = []
    for venv in _iter_venv_top_level_dirs(root):
        for dirpath, dirnames, filenames in os.walk(venv, topdown=True):
            current = Path(dirpath)
            for dirname in list(dirnames):
                if dirname in VENV_ARTIFACT_DIR_NAMES:
                    targets.append(current / dirname)
            dirnames[:] = [d for d in dirnames if d not in VENV_ARTIFACT_DIR_NAMES]
            for filename in filenames:
                if _matches_any(filename, VENV_ARTIFACT_FILE_GLOBS):
                    targets.append(current / filename)
    return targets


def _collect_paths(
    root: Path,
    *,
    keep_venvs: bool = False,
) -> list[Path]:
    targets: list[Path] = []

    for name in ROOT_DIRS:
        path = root / name
        if path.exists():
            targets.append(path)

    if keep_venvs:
        targets.extend(_collect_venv_artifacts(root))
    else:
        targets.extend(_iter_venv_top_level_dirs(root))

    for egg_info in root.glob("*.egg-info"):
        if egg_info.is_dir():
            targets.append(egg_info)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)

        if _is_under_venv(root, current):
            dirnames.clear()
            continue

        for dirname in list(dirnames):
            if dirname in WALK_DIR_NAMES or _matches_any(dirname, WALK_DIR_GLOBS):
                targets.append(current / dirname)

        skip_names = set(WALK_DIR_NAMES) | {d for d in dirnames if _matches_any(d, WALK_DIR_GLOBS)}
        skip_names |= {d for d in dirnames if _is_venv_top_level(d)}
        dirnames[:] = [d for d in dirnames if d not in skip_names]

        for filename in filenames:
            if _matches_any(filename, WALK_FILE_GLOBS):
                targets.append(current / filename)

    # Deduplicate: drop paths inside another target (keep outermost only).
    targets = sorted(set(targets), key=lambda p: (len(p.parts), str(p)))
    pruned: list[Path] = []
    for path in targets:
        if any(path != other and other in path.parents for other in targets):
            continue
        pruned.append(path)
    return sorted(pruned, key=lambda p: str(p))


def _format_size(path: Path) -> str:
    if path.is_file():
        return f"{path.stat().st_size} B"
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            with contextlib.suppress(OSError):
                total += p.stat().st_size
    if total < 1024:
        return f"{total} B"
    if total < 1024 * 1024:
        return f"{total / 1024:.1f} KiB"
    return f"{total / (1024 * 1024):.1f} MiB"


def _remove(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    if path.is_dir() and not path.is_symlink():
        def _onerror(func: object, name: str, _exc_info: object) -> None:
            # Clear read-only bits that commonly block rmtree on Windows checkouts.
            try:
                Path(name).chmod(0o700)
                func(name)  # type: ignore[operator]
            except OSError:
                pass

        shutil.rmtree(path, onerror=_onerror)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Remove build artifacts and temporary files from the repository tree.

    :param argv: Optional argument vector (defaults to ``sys.argv[1:]``).
    :type argv: list[str] | None, optional

    :returns: Process exit code (``0`` on success).
    :rtype: int
    """
    parser = argparse.ArgumentParser(description="Remove build artifacts and temporary files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List paths that would be removed without deleting anything",
    )
    parser.add_argument(
        "--keep-venvs",
        action="store_true",
        help=(
            "Keep top-level .venv/, .venv-*/, venv/, venv-*/, env/ "
            "(only scrub cache files inside)"
        ),
    )
    args = parser.parse_args(argv)
    root = _repo_root()

    targets = _collect_paths(root, keep_venvs=args.keep_venvs)
    if not targets:
        print("Nothing to clean.")
        return 0

    mode = "DRY RUN" if args.dry_run else "REMOVE"
    print(f"{mode}: {len(targets)} path(s) under {root}\n")
    for path in targets:
        rel = path.relative_to(root)
        try:
            size = _format_size(path) if path.exists() else "missing"
        except OSError:
            size = "?"
        print(f"  {rel}  ({size})")

    if args.dry_run:
        print("\nNo files were deleted. Re-run without --dry-run to remove.")
        return 0

    for path in targets:
        _remove(path, dry_run=False)
    print("\nCleanup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
