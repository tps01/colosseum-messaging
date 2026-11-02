"""Remote path normalization edges."""

from __future__ import annotations

from colosseum_messaging.ssh._remote_path import (
    normalize_remote_path,
    remote_basename,
    remote_dirname,
    split_remote_path,
)


def test_normalize_empty_and_drive_roots() -> None:
    assert normalize_remote_path("") == "/"
    assert normalize_remote_path("   ") == "/"
    assert normalize_remote_path("C:") == "C:/"
    assert normalize_remote_path("C:\\") == "C:/"
    assert normalize_remote_path("c:/logs\\a.txt") == "C:/logs/a.txt"


def test_split_dirname_basename_edges() -> None:
    assert split_remote_path("/logs/a.txt") == (None, ("logs", "a.txt"))
    assert split_remote_path("C:\\logs\\a.txt") == ("C", ("logs", "a.txt"))
    assert remote_dirname("/") == "/"
    assert remote_dirname("C:/") == "C:/"
    assert remote_dirname("/logs/a.txt") == "/logs"
    assert remote_dirname("C:/logs/a.txt") == "C:/logs"
    assert remote_basename("/") == ""
    assert remote_basename("C:/") == ""
    assert remote_basename("/logs/a.txt") == "a.txt"
