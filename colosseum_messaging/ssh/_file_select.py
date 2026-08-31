"""Remote and local file selection for SFTP/SCP transfers."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from colosseum_messaging.ssh._glob import fnmatch_name, path_has_glob
from colosseum_messaging.ssh._remote_path import (
    normalize_remote_path,
    remote_basename,
    remote_dirname,
    split_remote_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class RemoteLister(Protocol):
    def listdir_attr(self, path: str) -> Sequence[object]: ...

    def stat(self, path: str) -> object: ...


def _is_dir(mode: int | None) -> bool:
    return mode is not None and stat.S_ISDIR(mode)


def _join_remote(parent: str, name: str) -> str:
    if parent in ("/", ""):
        return normalize_remote_path(f"/{name}")
    return normalize_remote_path(f"{parent.rstrip('/')}/{name}")


def select_remote_files(
    lister: RemoteLister,
    remote: str,
    *,
    recursive: bool = False,
    max_depth: int | None = None,
    newest: int | None = None,
    oldest: int | None = None,
    case_sensitive: bool = True,
) -> list[tuple[str, float]]:
    if newest is not None and oldest is not None:
        raise ValueError("newest and oldest are mutually exclusive")

    normalized = normalize_remote_path(remote)
    pattern = remote_basename(normalized)
    parent = remote_dirname(normalized)
    has_glob = path_has_glob(pattern)
    results: list[tuple[str, float]] = []

    def add_file(path: str, mtime: float) -> None:
        results.append((path, mtime))

    def walk_dir(dir_path: str, depth: int, name_pattern: str | None) -> None:
        try:
            entries = lister.listdir_attr(dir_path)
        except OSError:
            return
        for attr in entries:
            name = str(getattr(attr, "filename", ""))
            if name in (".", ".."):
                continue
            child = _join_remote(dir_path, name)
            mode = getattr(attr, "st_mode", None)
            mtime = float(getattr(attr, "st_mtime", 0) or 0)
            if _is_dir(mode):
                if recursive and (max_depth is None or depth < max_depth):
                    walk_dir(child, depth + 1, None)
            elif name_pattern is None or fnmatch_name(
                name, name_pattern, case_sensitive=case_sensitive,
            ):
                add_file(child, mtime)

    if has_glob:
        walk_dir(parent, 0, pattern)
    elif not recursive:
        try:
            attr = lister.stat(normalized)
        except OSError as exc:
            raise FileNotFoundError(normalized) from exc
        mode = getattr(attr, "st_mode", None)
        if _is_dir(mode):
            raise ValueError(f"Remote path {normalized!r} is a directory; set recursive=True")
        add_file(normalized, float(getattr(attr, "st_mtime", 0) or 0))
    else:
        try:
            attr = lister.stat(normalized)
        except OSError as exc:
            raise FileNotFoundError(normalized) from exc
        mode = getattr(attr, "st_mode", None)
        if _is_dir(mode):
            walk_dir(normalized, 0, None)
        else:
            add_file(normalized, float(getattr(attr, "st_mtime", 0) or 0))

    if newest is not None:
        results.sort(key=lambda item: item[1], reverse=True)
        return results[: int(newest)]
    if oldest is not None:
        results.sort(key=lambda item: item[1])
        return results[: int(oldest)]
    return results


def select_local_files(
    local: str,
    *,
    recursive: bool = False,
    max_depth: int | None = None,
) -> list[tuple[Path, float]]:
    path = Path(local)
    if not path_has_glob(path.name):
        if path.is_file():
            return [(path.resolve(), path.stat().st_mtime)]
        if path.is_dir():
            if not recursive:
                raise ValueError(f"Local path {local!r} is a directory; set recursive=True")
            return _walk_local_dir(path.resolve(), depth=0, max_depth=max_depth)
        raise FileNotFoundError(local)

    parent = path.parent.resolve()
    pattern = path.name
    if not parent.is_dir():
        raise FileNotFoundError(str(parent))
    results: list[tuple[Path, float]] = []
    for child in parent.iterdir():
        if child.is_file() and fnmatch_name(child.name, pattern, case_sensitive=True):
            results.append((child, child.stat().st_mtime))
        elif child.is_dir() and recursive and (max_depth is None or max_depth > 0):
            results.extend(
                _walk_local_dir(child, depth=1, max_depth=max_depth, pattern=pattern),
            )
    return results


def _walk_local_dir(
    directory: Path,
    *,
    depth: int,
    max_depth: int | None,
    pattern: str | None = None,
) -> list[tuple[Path, float]]:
    results: list[tuple[Path, float]] = []
    for child in directory.iterdir():
        if child.is_file() and (
            pattern is None or fnmatch_name(child.name, pattern, case_sensitive=True)
        ):
            results.append((child, child.stat().st_mtime))
        elif child.is_dir() and (max_depth is None or depth < max_depth):
            results.extend(
                _walk_local_dir(child, depth=depth + 1, max_depth=max_depth, pattern=pattern),
            )
    return results


def map_remote_get_paths(
    remote_files: Sequence[str],
    remote_spec: str,
    local: str,
    *,
    resolve_local: Callable[[str], Path],
) -> list[tuple[str, Path]]:
    if not remote_files:
        return []

    normalized_spec = normalize_remote_path(remote_spec)
    base = remote_basename(normalized_spec)
    has_glob = path_has_glob(base)
    parent = remote_dirname(normalized_spec)
    multi = len(remote_files) > 1 or has_glob

    if not multi:
        return [(remote_files[0], resolve_local(local))]

    local_root = resolve_local(local)
    if local_root.suffix and not local.endswith(("/", "\\")):
        raise ValueError("local must be a directory when multiple remote files are selected")
    local_root.mkdir(parents=True, exist_ok=True)
    mapped: list[tuple[str, Path]] = []
    for remote_path in remote_files:
        rel = _relative_remote(parent, remote_path)
        if rel:
            dest = local_root / Path(*rel.split("/"))
        else:
            dest = local_root / remote_basename(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        mapped.append((remote_path, dest))
    return mapped


def map_local_put_paths(
    local_files: Sequence[Path],
    local_spec: str,
    remote: str,
) -> list[tuple[Path, str]]:
    if not local_files:
        return []

    remote_normalized = normalize_remote_path(remote)
    remote_name = remote_basename(remote_normalized)
    remote_parent = remote_dirname(remote_normalized)
    has_glob = path_has_glob(remote_name) or path_has_glob(Path(local_spec).name)
    multi = len(local_files) > 1 or has_glob

    if not multi:
        return [(local_files[0], remote_normalized)]

    mapped: list[tuple[Path, str]] = []
    local_root = Path(local_spec).parent.resolve()
    for local_path in local_files:
        try:
            rel = local_path.relative_to(local_root)
        except ValueError:
            rel = Path(local_path.name)
        remote_dest = _join_remote(remote_parent, rel.as_posix())
        mapped.append((local_path, remote_dest))
    return mapped


def _relative_remote(root: str, path: str) -> str:
    root_norm = normalize_remote_path(root).rstrip("/")
    path_norm = normalize_remote_path(path)
    if path_norm.startswith(root_norm + "/"):
        return path_norm[len(root_norm) + 1 :]
    _drive, parts = split_remote_path(path_norm)
    _root_drive, root_parts = split_remote_path(root_norm)
    if len(parts) > len(root_parts):
        return "/".join(parts[len(root_parts) :])
    return remote_basename(path_norm)
