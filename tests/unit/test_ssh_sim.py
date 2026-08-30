"""U-MSG-SSH: SSH sim stdout specification."""

from __future__ import annotations

from colosseum_messaging.ssh.client import SSHClientWrapper


def test_version_command_returns_semver_like_string() -> None:
    client = SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "pi"})
    out = client.exec_stdout("cat /etc/version")
    assert "v1.2.3" in out


def test_os_release_marker_command() -> None:
    client = SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "pi"})
    out = client.exec_stdout("test -f /etc/os-release && echo present")
    assert "present" in out
