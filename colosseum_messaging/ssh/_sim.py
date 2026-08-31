"""Simulated remote exec and SFTP filesystem."""

from __future__ import annotations

import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from colosseum_messaging.ssh._remote_path import normalize_remote_path, remote_basename

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass
class _SimNode:
    is_dir: bool = False
    content: bytes = b""
    mtime: float = field(default_factory=time.time)


class SimRemoteFS:
    def __init__(self) -> None:
        self._nodes: dict[str, _SimNode] = {"/": _SimNode(is_dir=True)}

    def _ensure_parent(self, path: str) -> None:
        normalized = normalize_remote_path(path)
        parts = [part for part in normalized.strip("/").split("/") if part]
        current = "/"
        for part in parts[:-1]:
            current = normalize_remote_path(f"{current.rstrip('/')}/{part}")
            node = self._nodes.get(current)
            if node is None:
                self._nodes[current] = _SimNode(is_dir=True)
            elif not node.is_dir:
                raise OSError("Not a directory")

    def put_file(self, remote: str, local_path: Path) -> None:
        normalized = normalize_remote_path(remote)
        self._ensure_parent(normalized)
        self._nodes[normalized] = _SimNode(
            is_dir=False,
            content=local_path.read_bytes(),
            mtime=local_path.stat().st_mtime,
        )

    def put_bytes(self, remote: str, payload: bytes) -> None:
        normalized = normalize_remote_path(remote)
        self._ensure_parent(normalized)
        self._nodes[normalized] = _SimNode(is_dir=False, content=payload)

    def get_file(self, remote: str, local_path: Path) -> None:
        normalized = normalize_remote_path(remote)
        node = self._nodes.get(normalized)
        if node is None or node.is_dir:
            raise FileNotFoundError(normalized)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(node.content)

    def remove(self, remote: str) -> None:
        normalized = normalize_remote_path(remote)
        if normalized not in self._nodes:
            raise FileNotFoundError(normalized)
        del self._nodes[normalized]

    def mkdir(self, remote: str) -> None:
        normalized = normalize_remote_path(remote)
        self._ensure_parent(normalized)
        self._nodes[normalized] = _SimNode(is_dir=True)

    def rename(self, old: str, new: str) -> None:
        old_norm = normalize_remote_path(old)
        new_norm = normalize_remote_path(new)
        node = self._nodes.get(old_norm)
        if node is None:
            raise FileNotFoundError(old_norm)
        self._ensure_parent(new_norm)
        self._nodes[new_norm] = node
        del self._nodes[old_norm]

    def listdir_attr(self, path: str) -> list[_SimAttr]:
        normalized = normalize_remote_path(path)
        node = self._nodes.get(normalized)
        if node is None or not node.is_dir:
            raise OSError("Not a directory")
        prefix = normalized.rstrip("/") + "/"
        names: set[str] = set()
        attrs: list[_SimAttr] = []
        for key, _child in self._nodes.items():
            if key == normalized:
                continue
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix) :]
            name = remainder.split("/")[0]
            if name in names:
                continue
            names.add(name)
            child_path = normalize_remote_path(f"{prefix}{name}")
            child_node = self._nodes[child_path]
            attrs.append(_SimAttr(name, child_node))
        return attrs

    def stat(self, path: str) -> _SimAttr:
        normalized = normalize_remote_path(path)
        node = self._nodes.get(normalized)
        if node is None:
            raise FileNotFoundError(normalized)
        return _SimAttr(remote_basename(normalized) or normalized, node)


@dataclass
class _SimAttr:
    filename: str
    _node: _SimNode

    @property
    def st_mode(self) -> int:
        return stat.S_IFDIR if self._node.is_dir else stat.S_IFREG

    @property
    def st_mtime(self) -> float:
        return self._node.mtime


def sim_exec_result(command: str, *, script_preview: str | None = None) -> dict[str, object]:
    cmd = command.strip()
    if script_preview is not None:
        preview = script_preview[:200]
        return {"exit_code": 0, "stdout": preview, "stderr": ""}
    if "version" in cmd:
        return {"exit_code": 0, "stdout": "v1.2.3", "stderr": ""}
    if "os-release" in cmd:
        return {"exit_code": 0, "stdout": "present", "stderr": ""}
    if "fail" in cmd.lower():
        return {"exit_code": 1, "stdout": "fail", "stderr": "error"}
    return {"exit_code": 0, "stdout": "ok", "stderr": ""}


def seed_sim_fs(fs: SimRemoteFS, config: Mapping[str, object]) -> None:
    platform = str(config.get("platform", "linux")).lower()
    if platform == "windows":
        fs.mkdir("C:/logs")
        fs.put_bytes("C:/logs/a.log", b"alpha")
        fs.put_bytes("C:/logs/b.log", b"beta")
        fs.put_bytes("C:/etc/network/interfaces", b"iface eth0")
    else:
        fs.mkdir("/var/log")
        fs.put_bytes("/var/log/a.log", b"alpha")
        fs.put_bytes("/var/log/b.log", b"beta")
        fs.put_bytes("/etc/network/interfaces", b"iface eth0")
