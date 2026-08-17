#!/usr/bin/env python3
"""Build an offline wheelhouse for this package (CI-agnostic).

Same entrypoint for GitHub Actions, Bamboo, or a local networked twin.
Produces first-party wheels plus ``pip download`` third-party deps for the
current OS / arch / Python.

Examples::

  python scripts/ci/build_offline_wheelhouse.py --zip

  # Plugins: include a sibling colosseum-core checkout in the house
  python scripts/ci/build_offline_wheelhouse.py --also-build ../colosseum-core --zip
"""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def _read_project_name(pyproject: Path) -> str:
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit(f"Could not read project name from {pyproject}")
    return match.group(1)


def _default_os_label() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "macos"
    return system or "unknown"


def _python_tag(py: str) -> str:
    out = subprocess.check_output(
        [py, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
        text=True,
    )
    return out.strip()


def _build_wheel(py: str, package_dir: Path, wheelhouse: Path) -> Path:
    if not (package_dir / "pyproject.toml").is_file():
        raise SystemExit(f"Missing pyproject.toml: {package_dir}")
    before = {p.name for p in wheelhouse.glob("*.whl")}
    _run([py, "-m", "build", "--wheel", "--outdir", str(wheelhouse)], cwd=package_dir)
    added = sorted(p for p in wheelhouse.glob("*.whl") if p.name not in before)
    if not added:
        raise SystemExit(f"No wheel produced for {package_dir}")
    return added[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        default=None,
        help="Output directory (default: <repo>/wheelhouse)",
    )
    parser.add_argument(
        "--also-build",
        type=Path,
        action="append",
        default=[],
        help="Extra package directory to build into the house (repeatable)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python used to build and download (default: current interpreter)",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Write <package>-offline-<os>-py<ver>.zip next to the wheelhouse",
    )
    parser.add_argument(
        "--os-label",
        default=None,
        help="OS token in zip name (default: windows/linux/macos from platform)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Directory for the zip (default: repo root)",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    py = args.python
    package_name = _read_project_name(root / "pyproject.toml")
    wheelhouse = (args.wheelhouse or (root / "wheelhouse")).resolve()
    os_label = args.os_label or _default_os_label()
    py_tag = _python_tag(py)

    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)

    # Prefer ensuring tools exist; avoid upgrading pip itself (breaks some locked installs).
    _run([py, "-m", "pip", "install", "setuptools", "wheel", "build"])

    # Build dependency packages first, then this package.
    first_party: list[Path] = []
    for extra in args.also_build:
        first_party.append(_build_wheel(py, extra.resolve(), wheelhouse))
    first_party.append(_build_wheel(py, root, wheelhouse))

    download_cmd = [
        py,
        "-m",
        "pip",
        "download",
        "-d",
        str(wheelhouse),
        "--find-links",
        str(wheelhouse),
        *[str(p) for p in first_party],
    ]
    _run(download_cmd)

    wheels = sorted(wheelhouse.glob("*.whl"))
    manifest = wheelhouse / "MANIFEST.txt"
    manifest.write_text(
        "\n".join(
            [
                f"package={package_name}",
                f"python={py_tag}",
                f"os_label={os_label}",
                f"created_utc={datetime.now(timezone.utc).isoformat()}",
                f"platform={platform.platform()}",
                f"machine={platform.machine()}",
                f"wheel_count={len(wheels)}",
                "",
                "wheels:",
                *[f"  {p.name}" for p in wheels],
                "",
                "first_party:",
                *[f"  {p.name}" for p in first_party],
                "",
            ]
        ),
        encoding="utf-8",
    )

    (wheelhouse / "INSTALL.txt").write_text(
        "\n".join(
            [
                f"Offline install (Python {py_tag}, {os_label}):",
                "",
                "  python -m venv .venv",
                "  # activate, then:",
                f"  python -m pip install --no-index --find-links=. {package_name}",
                "",
                "GUI (colosseum-core): tkinter must already be part of this Python.",
                "Windows python.org builds usually include it.",
                "Linux: bake python3-tk (or a Tk-enabled Python) into the host image.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Wheelhouse ready: {wheelhouse} ({len(wheels)} wheels)")

    if args.zip:
        archive_dir = (args.archive_dir or root).resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{package_name}-offline-{os_label}-py{py_tag}"
        archive_base = archive_dir / stem
        # make_archive adds .zip
        for stale in archive_dir.glob(f"{stem}.zip"):
            stale.unlink()
        zip_path = Path(shutil.make_archive(str(archive_base), "zip", wheelhouse))
        print(f"Archive: {zip_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
