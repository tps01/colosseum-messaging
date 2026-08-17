#!/usr/bin/env python3
"""Build sdist + wheel into dist/ (CI-agnostic).

  python scripts/ci/build_dist.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python used to build (default: current interpreter)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Output directory (default: <repo>/dist)",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    outdir = (args.outdir or (root / "dist")).resolve()
    py = args.python

    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    # Prefer ensuring tools exist; avoid upgrading pip itself (breaks some locked installs).
    cmd = [py, "-m", "pip", "install", "setuptools", "wheel", "build"]
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)

    cmd = [py, "-m", "build", "--outdir", str(outdir)]
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(root))

    built = sorted(outdir.iterdir())
    if not built:
        raise SystemExit(f"No distributions written to {outdir}")
    for path in built:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
