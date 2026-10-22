"""auth=none host-key checks against the file and the system store."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import paramiko
import pytest
from colosseum_messaging.ssh.client import SSHClientWrapper
from nacl.signing import VerifyKey
from paramiko.message import Message

if TYPE_CHECKING:
    from pathlib import Path


def _public_host_key() -> paramiko.PKey:
    verify = VerifyKey(os.urandom(32))
    message = Message()
    message.add_string("ssh-ed25519")
    message.add_string(verify.encode())
    return paramiko.Ed25519Key(data=message.asbytes())


def _write_known_host(path: Path, hostname: str, key: paramiko.PKey) -> None:
    path.write_text(f"{hostname} {key.get_name()} {key.get_base64()}\n", encoding="utf-8")


def _client(known_hosts: Path | None = None) -> SSHClientWrapper:
    config: dict[str, object] = {
        "driver": "sim",
        "host": "bench.example",
        "username": "u",
        "auth": "none",
    }
    if known_hosts is not None:
        config["known_hosts"] = str(known_hosts)
    return SSHClientWrapper(config)


def test_auth_none_trusts_explicit_known_hosts_file(tmp_path: Path) -> None:
    key = _public_host_key()
    known_hosts = tmp_path / "known_hosts"
    _write_known_host(known_hosts, "bench.example", key)
    _client(known_hosts)._require_known_host_key("bench.example", 22, key)


def test_auth_none_trusts_system_host_key_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _public_host_key()
    known_hosts = tmp_path / "system_known_hosts"
    _write_known_host(known_hosts, "bench.example", key)

    def _load(self: paramiko.SSHClient, filename: str | None = None) -> None:
        self._system_host_keys.load(str(known_hosts))

    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", _load)
    _client()._require_known_host_key("bench.example", 22, key)


def test_auth_none_rejects_unknown_host_key(tmp_path: Path) -> None:
    key = _public_host_key()
    known_hosts = tmp_path / "known_hosts"
    _write_known_host(known_hosts, "other.example", key)
    with pytest.raises(paramiko.SSHException, match="not in known_hosts"):
        _client(known_hosts)._require_known_host_key("bench.example", 22, key)


def test_auth_none_rejects_mismatched_file_and_system_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = _public_host_key()
    presented = _public_host_key()
    known_hosts = tmp_path / "known_hosts"
    _write_known_host(known_hosts, "bench.example", trusted)
    with pytest.raises(paramiko.SSHException, match="does not match"):
        _client(known_hosts)._require_known_host_key("bench.example", 22, presented)

    system_hosts = tmp_path / "system_known_hosts"
    _write_known_host(system_hosts, "bench.example", trusted)

    def _load(self: paramiko.SSHClient, filename: str | None = None) -> None:
        self._system_host_keys.load(str(system_hosts))

    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", _load)
    with pytest.raises(paramiko.SSHException, match="does not match"):
        _client()._require_known_host_key("bench.example", 22, presented)
