#!/usr/bin/env python3
"""Build GitHub Pages HTML for a Colosseum first-party plugin.

Configured via environment-free constants at the top of each plugin copy.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# --- per-plugin constants (edit when copying) ---
TITLE = "Colosseum Messaging"
SLUG = "messaging"
GUIDES: tuple[str, ...] = ()
# --- end per-plugin constants ---

HUB_URL = "https://tps01.github.io/colosseum-core/"
REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = REPO_ROOT / "build" / "pages"
SITE_SOURCE = BUILD_ROOT / "source"
HTML_DIR = BUILD_ROOT / "html"

_GUIDE_XREF_REPLACEMENTS = (
    (":doc:`configuration`", "the Colosseum **configuration** guide (core hub)"),
    (":doc:`platform_notes`", "Colosseum **platform notes** (core hub)"),
    ("**Bench configuration reference**", "**config TOML** sections documented by this plugin"),
)


def _read_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _pandoc_readme(dest: Path) -> None:
    readme = REPO_ROOT / "README.md"
    if not readme.is_file():
        raise SystemExit(f"Missing README: {readme}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pandoc", str(readme), "-f", "markdown", "-t", "rst", "-o", str(dest)],
        check=True,
    )


def _sanitize_guide(text: str) -> str:
    for old, new in _GUIDE_XREF_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _write_conf(version: str) -> None:
    pages_url = f"https://tps01.github.io/colosseum-{SLUG}/"
    conf = f'''"""Sphinx configuration for {TITLE} GitHub Pages."""

from __future__ import annotations

project = "{TITLE}"
copyright = "Colosseum contributors"
author = "Colosseum contributors"
release = "{version}"

master_doc = "index"
root_doc = "index"

extensions: list[str] = []

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_static_path = ["_static"]
html_baseurl = "{pages_url}"
'''
    (SITE_SOURCE / "conf.py").write_text(conf, encoding="utf-8")


def _write_index(guide_names: list[str]) -> None:
    lines = [
        TITLE,
        "=" * len(TITLE),
        "",
        f"First-party Colosseum plugin documentation (version from ``pyproject.toml``).",
        "",
        f"`Colosseum core documentation hub <{HUB_URL}>`__",
        "",
        ".. toctree::",
        "   :maxdepth: 2",
        "",
        "   readme",
    ]
    lines.extend(f"   {name}" for name in guide_names)
    lines.append("")
    (SITE_SOURCE / "index.rst").write_text("\n".join(lines), encoding="utf-8")
    (SITE_SOURCE / "_static").mkdir(exist_ok=True)


def stage() -> list[str]:
    if SITE_SOURCE.exists():
        shutil.rmtree(SITE_SOURCE)
    SITE_SOURCE.mkdir(parents=True)

    _pandoc_readme(SITE_SOURCE / "readme.rst")

    guide_names: list[str] = []
    guides_dir = SITE_SOURCE / "guides"
    for rel in GUIDES:
        src = REPO_ROOT / rel
        if not src.is_file():
            raise SystemExit(f"Missing guide: {src}")
        guides_dir.mkdir(parents=True, exist_ok=True)
        name = Path(rel).stem
        guide_names.append(f"guides/{name}")
        text = _sanitize_guide(src.read_text(encoding="utf-8"))
        (guides_dir / f"{name}.rst").write_text(text, encoding="utf-8")

    version = _read_version()
    _write_conf(version)
    _write_index(guide_names)
    return guide_names


def build_html() -> Path:
    stage()
    if HTML_DIR.exists():
        shutil.rmtree(HTML_DIR)
    HTML_DIR.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "html",
            "-W",
            "--keep-going",
            str(SITE_SOURCE),
            str(HTML_DIR),
        ],
        check=True,
    )
    (HTML_DIR / "version.txt").write_text(_read_version() + "\n", encoding="utf-8")
    return HTML_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Build {TITLE} GitHub Pages HTML")
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Stage Sphinx sources without building HTML",
    )
    args = parser.parse_args(argv)
    if args.stage_only:
        stage()
        print(SITE_SOURCE)
        return 0
    out = build_html()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
