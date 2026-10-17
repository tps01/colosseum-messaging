#!/usr/bin/env python3
"""Build GitHub Pages HTML for a Colosseum first-party plugin.

API reference (Sphinx autodoc) is primary; README/guides are secondary.
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
# (rst_stem, import_module, displayed col.* path)
API_MODULES: tuple[tuple[str, str, str], ...] = (
    ('http', 'colosseum_messaging.http.api', 'col.messaging.http'),
    ('redis', 'colosseum_messaging.redis.api', 'col.messaging.redis'),
    ('zmq', 'colosseum_messaging.zmq.api', 'col.messaging.zmq'),
    ('mqtt', 'colosseum_messaging.mqtt.api', 'col.messaging.mqtt'),
    ('ssh', 'colosseum_messaging.ssh.api', 'col.messaging.ssh'),
    ('scp', 'colosseum_messaging.scp.api', 'col.messaging.scp'),
)
# Optional single-function pages: (rst_stem, "module:qualname", displayed name)
API_FUNCTIONS: tuple[tuple[str, str, str], ...] = (
)
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

_MOCK_IMPORTS = (
    "clr",
    "System",
    "FlaUI",
    "mss",
    "Xlib",
    "pywinauto",
    "comtypes",
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
    mocks = ", ".join(f'"{name}"' for name in _MOCK_IMPORTS)
    conf = f'''"""Sphinx configuration for {TITLE} GitHub Pages."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

project = "{TITLE}"
copyright = "Colosseum contributors"
author = "Colosseum contributors"
release = "{version}"

master_doc = "index"
root_doc = "index"

extensions = ["sphinx.ext.autodoc"]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_static_path = ["_static"]
html_baseurl = "{pages_url}"

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {{
    "members": True,
    "undoc-members": False,
    "show-inheritance": False,
}}
autodoc_mock_imports = [{mocks}]
'''
    (SITE_SOURCE / "conf.py").write_text(conf, encoding="utf-8")


def _write_module_page(stem: str, module: str, col_path: str) -> str:
    api_dir = SITE_SOURCE / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    title = col_path
    body = f"""{title}
{"=" * len(title)}

User-facing APIs under ``{col_path}`` (``import colosseum as col``).

.. automodule:: {module}
   :members:
   :exclude-members: get_logger
"""
    (api_dir / f"{stem}.rst").write_text(body, encoding="utf-8")
    return f"api/{stem}"


def _write_function_page(stem: str, target: str, col_path: str) -> str:
    api_dir = SITE_SOURCE / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    title = col_path
    body = f"""{title}
{"=" * len(title)}

.. autofunction:: {target}
"""
    (api_dir / f"{stem}.rst").write_text(body, encoding="utf-8")
    return f"api/{stem}"


def _write_index(api_docs: list[str], guide_names: list[str]) -> None:
    lines = [
        TITLE,
        "=" * len(TITLE),
        "",
        "API reference for this first-party Colosseum plugin. Start here for",
        "``col.*`` callables; use the overview for install notes and examples.",
        "",
        f"`Colosseum core documentation hub <{HUB_URL}>`__",
        "",
        ".. toctree::",
        "   :maxdepth: 2",
        "   :caption: API reference",
        "",
    ]
    lines.extend(f"   {doc}" for doc in api_docs)
    lines.extend(
        [
            "",
            ".. toctree::",
            "   :maxdepth: 2",
            "   :caption: Overview",
            "",
            "   readme",
        ]
    )
    if guide_names:
        lines.append("")
        lines.extend(
            [
                ".. toctree::",
                "   :maxdepth: 2",
                "   :caption: Guides",
                "",
            ]
        )
        lines.extend(f"   {name}" for name in guide_names)
    lines.append("")
    (SITE_SOURCE / "index.rst").write_text("\n".join(lines), encoding="utf-8")
    (SITE_SOURCE / "_static").mkdir(exist_ok=True)


def stage() -> None:
    if SITE_SOURCE.exists():
        shutil.rmtree(SITE_SOURCE)
    SITE_SOURCE.mkdir(parents=True)

    _pandoc_readme(SITE_SOURCE / "readme.rst")

    api_docs: list[str] = []
    for stem, module, col_path in API_MODULES:
        api_docs.append(_write_module_page(stem, module, col_path))
    for stem, target, col_path in API_FUNCTIONS:
        api_docs.append(_write_function_page(stem, target, col_path))
    if not api_docs:
        raise SystemExit("API_MODULES / API_FUNCTIONS must list at least one public API")

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

    _write_conf(_read_version())
    _write_index(api_docs, guide_names)


def build_html() -> Path:
    stage()
    if HTML_DIR.exists():
        shutil.rmtree(HTML_DIR)
    HTML_DIR.mkdir(parents=True)
    # Do not treat every autodoc nit as fatal; keep going for partial import issues.
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
