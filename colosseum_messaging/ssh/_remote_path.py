"""Remote path normalization for Linux and Windows OpenSSH hosts."""

from __future__ import annotations

import re

_DRIVE_PREFIX = re.compile(r"^([A-Za-z]):[/\\]?")


def split_remote_path(path: str) -> tuple[str | None, tuple[str, ...]]:
    """Split a remote path into an optional drive letter and path parts."""
    text = path.strip()
    drive: str | None = None
    match = _DRIVE_PREFIX.match(text)
    if match:
        drive = match.group(1).upper()
        text = text[match.end() :]
    parts = [part for part in re.split(r"[/\\]+", text) if part]
    return drive, tuple(parts)


def normalize_remote_path(path: str) -> str:
    """Normalize a remote path to SFTP-style forward slashes."""
    drive, parts = split_remote_path(path)
    if drive is None:
        if not parts:
            return "/"
        return "/" + "/".join(parts)
    if not parts:
        return f"{drive}:/"
    return f"{drive}:/" + "/".join(parts)


def remote_dirname(path: str) -> str:
    drive, parts = split_remote_path(path)
    if not parts:
        return normalize_remote_path(f"{drive}:" if drive else "/")
    parent = parts[:-1]
    if drive is None:
        if not parent:
            return "/"
        return "/" + "/".join(parent)
    if not parent:
        return f"{drive}:/"
    return f"{drive}:/" + "/".join(parent)


def remote_basename(path: str) -> str:
    _drive, parts = split_remote_path(path)
    if not parts:
        return ""
    return parts[-1]
