"""Output path helpers for messaging plugin artifacts."""

from __future__ import annotations

from pathlib import Path

from colosseum.context import get_context
from colosseum.runner.paths import ensure_output_dir


def resolve_artifact_path(relative_path: str) -> Path:
    """Return a path inside the active run directory and create its parent.

    The candidate is resolved first, then accepted only when ``relative_to``
    succeeds. A sibling directory whose name shares a string prefix (``run``
    versus ``run-other``) is outside the run. Absolute paths are checked the
    same way, so a download destination built from an accepted root must be
    passed back through this function.
    """
    ctx = get_context()
    root = ensure_output_dir(ctx, logical_name=ctx.test_case_name).resolve()
    candidate = Path(relative_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            "Artifact path must remain inside the active output directory",
        ) from None
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
