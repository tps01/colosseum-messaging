"""U-MSG-SSH: SSH sim stdout specification."""

from __future__ import annotations

import paramiko
from colosseum_messaging.ssh.client import SSHClientWrapper


def test_version_command_returns_semver_like_string() -> None:
    client = SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "pi"})
    out = client.exec_stdout("cat /etc/version")
    assert "v1.2.3" in out


def test_os_release_marker_command() -> None:
    client = SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "pi"})
    out = client.exec_stdout("test -f /etc/os-release && echo present")
    assert "present" in out


def test_ssh_rejects_unknown_host_keys_by_default(monkeypatch) -> None:
    policies: list[str] = []

    class _FakeClient:
        def load_system_host_keys(self) -> None:
            return None

        def load_host_keys(self, path: str) -> None:
            return None

        def set_missing_host_key_policy(self, policy: object) -> None:
            policies.append(type(policy).__name__)

        def connect(self, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(paramiko, "SSHClient", _FakeClient)
    SSHClientWrapper(
        {"driver": "ssh", "host": "dut.local", "username": "pi", "password": "secret"},
    )
    assert policies == ["RejectPolicy"]
