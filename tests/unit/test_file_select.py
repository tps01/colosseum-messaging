"""SFTP/SCP selection and upload destination mapping."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from colosseum_messaging.ssh._file_select import (
    map_local_put_paths,
    select_local_files,
    select_remote_files,
)
from colosseum_messaging.ssh._remote_path import normalize_remote_path

if TYPE_CHECKING:
    from pathlib import Path


class _Attr:
    def __init__(self, filename: str, mode: int) -> None:
        self.filename = filename
        self.st_mode = mode
        self.st_mtime = 1.0


class _Lister:
    def __init__(self) -> None:
        self._dirs = {
            "/logs": [
                _Attr("a.log", stat.S_IFREG),
                _Attr("note.txt", stat.S_IFREG),
                _Attr("sub", stat.S_IFDIR),
            ],
            "/logs/sub": [
                _Attr("b.log", stat.S_IFREG),
                _Attr("secret.bin", stat.S_IFREG),
            ],
        }

    def listdir_attr(self, path: str) -> list[_Attr]:
        return self._dirs[normalize_remote_path(path)]

    def stat(self, path: str) -> _Attr:
        raise FileNotFoundError(path)


def _remotes(local_spec: str, remote: str, *, recursive: bool = False) -> set[str]:
    selected = [
        path for path, _mtime in select_local_files(local_spec, recursive=recursive)
    ]
    return {dest for _path, dest in map_local_put_paths(selected, local_spec, remote)}


def test_one_file_without_slash_is_a_rename(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("a", encoding="utf-8")
    assert _remotes(str(source), "/target/only.txt") == {"/target/only.txt"}


def test_trailing_slash_keeps_one_or_many_files_in_the_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("b", encoding="utf-8")
    one = _remotes(str(source / "a.txt"), "/target/")
    assert one == {"/target/a.txt"}
    many = _remotes(str(source / "*.txt"), "/target/")
    assert many == {"/target/a.txt", "/target/b.txt"}
    unsuffixed = _remotes(str(source / "*.txt"), "/target")
    assert unsuffixed == {"/target/a.txt", "/target/b.txt"}


def test_recursive_upload_preserves_paths_under_the_remote_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "sub").mkdir(parents=True)
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "sub" / "b.txt").write_text("b", encoding="utf-8")
    remotes = _remotes(str(source), "/target/", recursive=True)
    assert remotes == {"/target/a.txt", "/target/sub/b.txt"}


def test_windows_drive_destination_keeps_the_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("b", encoding="utf-8")
    assert _remotes(str(source / "*.txt"), "C:/target/") == {
        "C:/target/a.txt",
        "C:/target/b.txt",
    }
    assert _remotes(str(source / "*.txt"), "C:\\target\\") == {
        "C:/target/a.txt",
        "C:/target/b.txt",
    }


def test_recursive_remote_glob_filters_basenames() -> None:
    found = {
        path
        for path, _mtime in select_remote_files(_Lister(), "/logs/*.log", recursive=True)
    }
    assert found == {"/logs/a.log", "/logs/sub/b.log"}


def test_recursive_local_glob_filters_basenames(tmp_path: Path) -> None:
    root = tmp_path / "logs"
    (root / "sub").mkdir(parents=True)
    (root / "a.log").write_text("a", encoding="utf-8")
    (root / "note.txt").write_text("n", encoding="utf-8")
    (root / "sub" / "b.log").write_text("b", encoding="utf-8")
    (root / "sub" / "secret.bin").write_text("no", encoding="utf-8")
    found = {path.name for path, _mtime in select_local_files(str(root / "*.log"), recursive=True)}
    assert found == {"a.log", "b.log"}
