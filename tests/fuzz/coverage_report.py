"""Manually replay fuzz seeds with scoped line/branch coverage; no Atheris needed."""

from __future__ import annotations

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = "remote_selection"
MODULES = [
    "colosseum_messaging/_paths.py",
    "colosseum_messaging/ssh/_remote_path.py",
    "colosseum_messaging/ssh/_file_select.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, help="Default: tests/fuzz/corpus")
    parser.add_argument("--output", type=Path, help="Default: .fuzz-work/coverage/" + TARGET)
    args = parser.parse_args()
    corpus = (args.corpus or REPO / "tests/fuzz/corpus").resolve()
    if not corpus.is_dir():
        parser.error(f"Corpus directory does not exist: {corpus}")
    inputs = sorted(path for path in corpus.iterdir() if path.is_file())
    if not inputs:
        parser.error(f"Corpus directory has no inputs: {corpus}")
    output = (args.output or REPO / ".fuzz-work/coverage" / TARGET).resolve()
    output.mkdir(parents=True, exist_ok=True)

    from coverage import Coverage

    coverage = Coverage(
        data_file=str(output / ".coverage"),
        branch=True,
        include=[str(REPO / module) for module in MODULES],
        config_file=False,
    )
    coverage.start()
    try:
        spec = spec_from_file_location("fuzz_target", REPO / "tests/fuzz" / (TARGET + ".py"))
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        module.check_input(b"")
        for seed in inputs:
            print(f"Replaying {seed}")
            module.check_input(seed.read_bytes())
    finally:
        coverage.stop()
        coverage.save()
    coverage.json_report(outfile=str(output / "coverage.json"), pretty_print=True)
    coverage.html_report(directory=str(output / "html"))
    coverage.report(show_missing=True)
    print(f"Replayed {len(inputs)} corpus files plus the empty input. Reports: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
