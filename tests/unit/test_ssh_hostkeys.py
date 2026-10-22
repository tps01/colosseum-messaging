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


@pytest.mark.parametrize("store", ["system", "missing", "empty", "known", "other_host"])
@pytest.mark.parametrize("port", [22, 2222])
def test_auth_auto_reaches_login_for_known_and_new_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: str, port: int,
) -> None:
    from unittest.mock import Mock

    key = _public_host_key()
    host_id = "bench.example" if port == 22 else f"[bench.example]:{port}"
    config = {
        "host": "bench.example", "port": port, "username": "u",
        "password": "password", "auth": "auto",
    }
    known_hosts = tmp_path / "ssh" / "known_hosts"
    if store != "system":
        if store != "missing":
            known_hosts.parent.mkdir()
            known_hosts.write_text("", encoding="utf-8")
        if store in ("known", "other_host"):
            _write_known_host(known_hosts, host_id if store == "known" else "other", key)
        config["known_hosts"] = str(known_hosts)
    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", lambda self: None)
    # Exercise Paramiko's real host-key validation and policy dispatch without a network.
    transport = Mock(spec=paramiko.Transport)
    transport.gss_kex_used = False
    transport.gss_host = "bench.example"
    transport.get_security_options.return_value.key_types = (key.get_name(),)
    transport.get_remote_server_key.return_value = key
    real_connect = paramiko.SSHClient.connect

    def connect(self, **kwargs):
        real_connect(self, sock=Mock(), transport_factory=lambda *a, **kw: transport, **kwargs)

    authenticate = Mock()
    monkeypatch.setattr(paramiko.SSHClient, "connect", connect)
    monkeypatch.setattr(paramiko.SSHClient, "_auth", authenticate)
    client = SSHClientWrapper(config)
    try:
        authenticate.assert_called_once()
        assert authenticate.call_args.args[:2] == ("u", "password")
        if store != "system":
            assert paramiko.HostKeys(str(known_hosts)).check(host_id, key)
        else:
            assert client._require_client().get_host_keys().check(host_id, key)
    finally:
        client.close()
