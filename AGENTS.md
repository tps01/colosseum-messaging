# AGENTS.md

Baseline expectations for AI agents in this plugin repository.

## Purpose

- This is a first-party Colosseum plugin. Development, packaging, and usage
  follow the same entry-point specification as third-party plugins.
- Depends only on `colosseum-core` as declared in `pyproject.toml` (plugins must
  not depend on each other).
- User import remains `import colosseum as col`; this package registers
  namespaces via `colosseum.plugins`.

## Change discipline

Prefer focused, compact changes. Do not commit unless asked. Read `RULES.md` at
task start.

## Footprint

Follow the workspace **Minimizing footprint** section (top-level `AGENTS.md`).
Inventory
existing code before adding files; prefer merge, relocate, or delete over new
modules.
Keep plugin-only helpers local (e.g. `_paths.py`, `_cache.py`)—do not expand
core for
single-plugin needs.

## Workflow

When completing changes, increment the package version in `pyproject.toml` using
semantic versioning. Agents cannot increment the major number.

When finishing a development session: `python scripts/cleanup.py --dry-run`,
then
`python scripts/cleanup.py` if the list looks right. See workspace `AGENTS.md`
(**Simulated annealing**, **End-of-development cleanup**).
