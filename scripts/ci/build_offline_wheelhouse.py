#!/usr/bin/env python3
"""Build an offline wheelhouse for this package (CI-agnostic).

Same entrypoint for GitHub Actions, Bamboo, or a local networked twin.
Produces first-party wheels plus ``pip download`` third-party deps for the
current OS / arch / Python.

Bundle layout::

  <wheelhouse>/
    wheels/*.whl
    MANIFEST.txt
    INSTALL.txt
    install.bat / install.sh
    start_cli.bat / start_cli.sh
    start_gui.bat / start_gui.sh

Archives: Windows → ``.zip``; Linux/macOS → ``.tar.gz``.

Examples::

  python scripts/ci/build_offline_wheelhouse.py --archive

  # Plugins: include a sibling colosseum-core checkout in the house
  python scripts/ci/build_offline_wheelhouse.py --also-build ../colosseum-core --archive
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


def _archive_format(os_label: str) -> str:
    """``shutil.make_archive`` format: zip on Windows, gztar elsewhere."""
    if os_label == "windows":
        return "zip"
    return "gztar"


def _build_wheel(py: str, package_dir: Path, wheels_dir: Path) -> Path:
    if not (package_dir / "pyproject.toml").is_file():
        raise SystemExit(f"Missing pyproject.toml: {package_dir}")
    before = {p.name for p in wheels_dir.glob("*.whl")}
    _run([py, "-m", "build", "--wheel", "--outdir", str(wheels_dir)], cwd=package_dir)
    added = sorted(p for p in wheels_dir.glob("*.whl") if p.name not in before)
    if not added:
        raise SystemExit(f"No wheel produced for {package_dir}")
    return added[-1]


def _write_bundle_scripts(wheelhouse: Path, packages: list[str]) -> None:
    """Write install / start helpers at the bundle root (wheels stay nested)."""
    pkg_list = " ".join(packages)

    (wheelhouse / "install.bat").write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                'cd /d "%~dp0"',
                "if not exist .venv (",
                "  echo Creating virtual environment .venv ...",
                "  python -m venv .venv",
                "  if errorlevel 1 exit /b 1",
                ")",
                'call "%~dp0.venv\\Scripts\\activate.bat"',
                "python -m pip install --upgrade pip",
                f'python -m pip install --no-index --find-links="%~dp0wheels" {pkg_list}',
                "if errorlevel 1 exit /b 1",
                "echo.",
                "echo Offline install complete.",
                "echo   CLI operators:  start_cli.bat",
                "echo   GUI operators:  start_gui.bat",
                "endlocal",
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    (wheelhouse / "install.sh").write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'ROOT="$(cd "$(dirname "$0")" && pwd)"',
                'cd "$ROOT"',
                'if [[ ! -d .venv ]]; then',
                '  echo "Creating virtual environment .venv ..."',
                "  python3 -m venv .venv",
                "fi",
                '# shellcheck disable=SC1091',
                'source "$ROOT/.venv/bin/activate"',
                "python -m pip install --upgrade pip",
                f'python -m pip install --no-index --find-links="$ROOT/wheels" {pkg_list}',
                "echo",
                'echo "Offline install complete."',
                'echo "  CLI operators:  ./start_cli.sh"',
                'echo "  GUI operators:  ./start_gui.sh"',
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    (wheelhouse / "start_cli.bat").write_text(
        "\r\n".join(
            [
                "@echo off",
                'cd /d "%~dp0"',
                'if not exist "%~dp0.venv\\Scripts\\activate.bat" (',
                "  echo Run install.bat first.",
                "  exit /b 1",
                ")",
                'call "%~dp0.venv\\Scripts\\activate.bat"',
                "echo Colosseum CLI environment active. Try: colosseum --help",
                "cmd /k",
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    (wheelhouse / "start_cli.sh").write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'ROOT="$(cd "$(dirname "$0")" && pwd)"',
                'if [[ ! -f "$ROOT/.venv/bin/activate" ]]; then',
                '  echo "Run ./install.sh first." >&2',
                "  exit 1",
                "fi",
                '# shellcheck disable=SC1091',
                'source "$ROOT/.venv/bin/activate"',
                'echo "Colosseum CLI environment active. Try: colosseum --help"',
                'exec "${SHELL:-bash}" -i',
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    (wheelhouse / "start_gui.bat").write_text(
        "\r\n".join(
            [
                "@echo off",
                'cd /d "%~dp0"',
                'if not exist "%~dp0.venv\\Scripts\\activate.bat" (',
                "  echo Run install.bat first.",
                "  exit /b 1",
                ")",
                'call "%~dp0.venv\\Scripts\\activate.bat"',
                "colosseum --gui",
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    (wheelhouse / "start_gui.sh").write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'ROOT="$(cd "$(dirname "$0")" && pwd)"',
                'if [[ ! -f "$ROOT/.venv/bin/activate" ]]; then',
                '  echo "Run ./install.sh first." >&2',
                "  exit 1",
                "fi",
                '# shellcheck disable=SC1091',
                'source "$ROOT/.venv/bin/activate"',
                "exec colosseum --gui",
                "",
            ],
        ),
        encoding="utf-8",
        newline="\n",
    )

    # Best-effort executable bit for Unix hosts that extract the archive.
    for name in ("install.sh", "start_cli.sh", "start_gui.sh"):
        path = wheelhouse / name
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass


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
        "--archive",
        "--zip",
        dest="archive",
        action="store_true",
        help=(
            "Write an archive next to the wheelhouse "
            "(Windows: .zip; Linux/macOS: .tar.gz). --zip is an alias."
        ),
    )
    parser.add_argument(
        "--os-label",
        default=None,
        help="OS token in archive name (default: windows/linux/macos from platform)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Directory for the archive (default: repo root)",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    py = args.python
    package_name = _read_project_name(root / "pyproject.toml")
    wheelhouse = (args.wheelhouse or (root / "wheelhouse")).resolve()
    wheels_dir = wheelhouse / "wheels"
    os_label = args.os_label or _default_os_label()
    py_tag = _python_tag(py)

    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheels_dir.mkdir(parents=True)

    # Prefer ensuring tools exist; avoid upgrading pip itself (breaks some locked installs).
    _run([py, "-m", "pip", "install", "setuptools", "wheel", "build"])

    # Build dependency packages first, then this package.
    first_party: list[Path] = []
    install_names: list[str] = []
    for extra in args.also_build:
        wheel = _build_wheel(py, extra.resolve(), wheels_dir)
        first_party.append(wheel)
        install_names.append(_read_project_name(extra.resolve() / "pyproject.toml"))
    first_party.append(_build_wheel(py, root, wheels_dir))
    install_names.append(package_name)
    # Prefer installing the primary package last so pip resolves it as the goal.
    # Deduplicate while preserving order (core may appear twice if also-build).
    seen: set[str] = set()
    unique_install: list[str] = []
    for name in install_names:
        if name not in seen:
            seen.add(name)
            unique_install.append(name)

    download_cmd = [
        py,
        "-m",
        "pip",
        "download",
        "-d",
        str(wheels_dir),
        "--find-links",
        str(wheels_dir),
        *[str(p) for p in first_party],
    ]
    _run(download_cmd)

    wheels = sorted(wheels_dir.glob("*.whl"))
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
                *[f"  wheels/{p.name}" for p in wheels],
                "",
                "first_party:",
                *[f"  wheels/{p.name}" for p in first_party],
                "",
            ],
        ),
        encoding="utf-8",
    )

    _write_bundle_scripts(wheelhouse, unique_install)

    archive_note = (
        "Windows archive: .zip — extract, then run install.bat"
        if os_label == "windows"
        else "Linux/macOS archive: .tar.gz — extract, then run ./install.sh"
    )
    (wheelhouse / "INSTALL.txt").write_text(
        "\n".join(
            [
                f"Offline install (Python {py_tag}, {os_label}):",
                "",
                "1. Extract this archive on a matching OS / Python minor.",
                "2. Create a venv and install from the nested wheels/ folder:",
                "",
                "   Windows:  install.bat",
                "   Linux:    chmod +x install.sh start_*.sh && ./install.sh",
                "",
                "3. Day-to-day use:",
                "",
                "   CLI operators:  start_cli.bat   or  ./start_cli.sh",
                "   GUI operators:  start_gui.bat   or  ./start_gui.sh",
                "",
                "Manual equivalent:",
                "",
                "  python -m venv .venv",
                "  # activate, then:",
                f"  python -m pip install --no-index --find-links=wheels {package_name}",
                "",
                archive_note,
                "",
                "GUI (colosseum-core): tkinter must already be part of this Python.",
                "Windows python.org builds usually include it.",
                "Linux: bake python3-tk (or a Tk-enabled Python) into the host image.",
                "",
            ],
        ),
        encoding="utf-8",
    )

    print(f"Wheelhouse ready: {wheelhouse} ({len(wheels)} wheels in wheels/)")

    if args.archive:
        archive_dir = (args.archive_dir or root).resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{package_name}-offline-{os_label}-py{py_tag}"
        archive_base = archive_dir / stem
        fmt = _archive_format(os_label)
        for stale in archive_dir.glob(f"{stem}.zip"):
            stale.unlink()
        for stale in archive_dir.glob(f"{stem}.tar.gz"):
            stale.unlink()
        archive_path = Path(
            shutil.make_archive(str(archive_base), fmt, root_dir=wheelhouse),
        )
        print(f"Archive: {archive_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
