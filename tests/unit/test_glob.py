"""Glob helpers for messaging file selection."""

from __future__ import annotations

from colosseum_messaging.ssh._glob import fnmatch_name, path_has_glob


def test_path_has_glob_detects_wildcards() -> None:
    assert path_has_glob("*.log") is True
    assert path_has_glob("file?.txt") is True
    assert path_has_glob("file[ab].txt") is True
    assert path_has_glob("plain.txt") is False


def test_fnmatch_name_case_fold() -> None:
    assert fnmatch_name("App.LOG", "*.log", case_sensitive=True) is False
    assert fnmatch_name("App.LOG", "*.log", case_sensitive=False) is True
    assert fnmatch_name("App.LOG", "*.LOG", case_sensitive=True) is True
