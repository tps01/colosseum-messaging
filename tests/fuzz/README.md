# Starter fuzz target

`remote_selection.py` exposes `check_input(bytes)` for both pytest seed replay and Atheris.
Inputs are bounded to 512 bytes. No external services or devices are used.

Run the checked-in corpus on any supported platform:

```sh
python -m pytest tests/unit/test_fuzz_seeds.py -q
```

For coverage-guided mutation, use an isolated Linux x86_64 Python 3.12 developer
installation (`pip install -r requirements.txt`). Atheris is Apache-2.0 licensed
and a developer dependency only. From the repository root:

```sh
mkdir -p .fuzz-work/corpus .fuzz-work/artifacts
cp tests/fuzz/corpus/* .fuzz-work/corpus/
python tests/fuzz/remote_selection.py .fuzz-work/corpus -max_total_time=30 -max_len=512 -timeout=5 -artifact_prefix=.fuzz-work/artifacts/
```

The working corpus can grow; only deliberate seeds belong in `tests/fuzz/corpus`.
Replay a finding by passing its file instead of the corpus directory. Preserve
confirmed bugs as named regression tests. Longer mutation runs are manual;
ordinary pytest/CI replays the checked-in seeds without importing Atheris.

Checks a generated tree against a flat selection model: glob filtering, case,
recursion/depth, newest/oldest ordering and limits. Also checks Windows/POSIX
path equivalence for generated paths. It does not contact SSH or transfer files.

## Manual coverage reports

Use an isolated project developer environment with `coverage>=7.6` installed
from `requirements.txt`. Avoid upgrading the shared mutation-testing environment,
which requires an older coverage.py. Atheris is not needed for these reports.

```sh
python tests/fuzz/coverage_report.py
python tests/fuzz/coverage_report.py --corpus .fuzz-work/corpus --output .fuzz-work/coverage/explored
```

The default command replays the tracked corpus plus the empty input and writes
`.coverage`, `coverage.json`, and `html/index.html` under
`.fuzz-work/coverage/remote_selection/`. Reports include production line and branch
coverage, exclude the fuzz harness, and print missing lines to the terminal.
The custom corpus command can measure inputs retained by a longer fuzz session.

Reports are manual diagnostics, with no CI job or coverage threshold. Percentages
cover the whole selected production modules, including functions outside this
starter target. A higher percentage alone does not establish correctness.

## Broader input checks and retained corpora

Destination checks now exercise real upload/download mapping and the production
artifact path guard in isolated temporary directories. They check nested layout,
single-file rename, trailing-slash directory behavior, constructed-child
confinement, sibling-prefix traversal, and rejection of a file destination for
a glob. No SSH connection or actual file transfer occurs.

For a longer manual session on Linux Python 3.12:

```sh
python tests/fuzz/run.py --seconds 60
```

The runner adds missing tracked seeds without clearing `.fuzz-work/corpus`,
appends engine output to `.fuzz-work/fuzz.log`, preserves crash artifacts, and
reports coverage of the accumulated corpus in `.fuzz-work/coverage/explored`.
Repeat the command to continue exploration with prior discoveries. Use `--work`
for a separate campaign. A failing engine returns failure without deleting its
inputs. The time budget can overrun while the final input finishes.

Compare the explored report with the tracked-seed report from
`python tests/fuzz/coverage_report.py`. Replay and promote small inputs that
reach useful new behavior or reproduce bugs; do not check in the whole generated
corpus. The persistent corpus is local/ignored; back it up separately if needed.
Long runs and coverage remain manual, with no new CI job or threshold.
