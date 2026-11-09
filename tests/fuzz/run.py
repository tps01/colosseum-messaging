"""Run a bounded fuzz session while retaining the working corpus between runs."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = "remote_selection"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--work", type=Path, default=REPO / ".fuzz-work")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    work = args.work.resolve()
    corpus, artifacts = work / "corpus", work / "artifacts"
    corpus.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    # Never clear the working corpus; libFuzzer retains inputs that add features.
    for seed in (REPO / "tests/fuzz/corpus").iterdir():
        if seed.is_file():
            destination = corpus / seed.name
            if not destination.exists():
                shutil.copyfile(seed, destination)
    log_path = work / "fuzz.log"
    print(f"Running {TARGET} for {args.seconds}s. Corpus: {corpus}. Log: {log_path}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        command = [
            sys.executable,
            str(REPO / "tests/fuzz" / (TARGET + ".py")),
            str(corpus),
            f"-max_total_time={args.seconds}",
            "-max_len=512",
            "-timeout=5",
            "-artifact_prefix=" + str(artifacts) + "/",
        ]
        result = subprocess.run(
            command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=False,
        )
    if result.returncode:
        print(f"Fuzzing failed ({result.returncode}); inspect {log_path} and {artifacts}")
        return result.returncode
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "tests/fuzz/coverage_report.py"),
            "--corpus",
            str(corpus),
            "--output",
            str(work / "coverage/explored"),
        ],
        cwd=REPO,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
