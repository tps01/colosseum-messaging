"""Glob matching for remote and local file selection."""

from __future__ import annotations

import fnmatch


def path_has_glob(component: str) -> bool:
    return any(char in component for char in "*?[")


def fnmatch_name(name: str, pattern: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return fnmatch.fnmatchcase(name, pattern)
    return fnmatch.fnmatchcase(name.lower(), pattern.lower())
