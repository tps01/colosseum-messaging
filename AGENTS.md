# AGENTS.md

Baseline expectations for AI agents in this plugin repository.

## Purpose

- This is a first-party Colosseum plugin. Development, packaging, and usage follow the same entry-point contract as third-party plugins.
- Depends only on `colosseum-core` as declared in `pyproject.toml` (plugins must not depend on each other).
- User import remains `import colosseum as col`; this package registers namespaces via `colosseum.plugins`.

## Change discipline

Prefer focused, compact changes. Do not commit unless asked. Read `RULES.md` at task start.

## Workflow

When completing changes, increment the package version in `pyproject.toml` using semantic versioning. Agents cannot increment the major number.
