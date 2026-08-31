"""U-MSG-SSH: expanded SSH/SFTP/SCP sim specifications."""

from __future__ import annotations

from pathlib import Path

import pytest
from colosseum.config import load_config
from colosseum_messaging.scp.client import ScpClientWrapper
from colosseum_messaging.ssh.client import SSHClientWrapper


@pytest.fixture
def sim_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SSHClientWrapper:
    config_path = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "configs"
        / "config.messaging.sim.toml"
    )
    monkeypatch.chdir(tmp_path)
    load_config(config_path)
    return SSHClientWrapper({"driver": "sim", "host": "sim.local", "username": "pi"})


def test_exec_returns_exit_stdout_stderr(sim_client: SSHClientWrapper) -> None:
    result = sim_client.exec("echo fail")
    assert result["exit_code"] == 1
    assert result["stdout"] == "fail"
    assert result["stderr"] == "error"


def test_exec_sequence_inline_preserves_special_chars(sim_client: SSHClientWrapper) -> None:
    script = "echo /tmp/a/b/*\n"
    result = sim_client.exec_sequence(script=script)
    assert "/tmp/a/b/*" in str(result["stdout"])


def test_exec_sequence_from_local_file(tmp_path: Path, sim_client: SSHClientWrapper) -> None:
    script_path = tmp_path / "run.sh"
    script_path.write_text("echo $HOME\n", encoding="utf-8")
    result = sim_client.exec_sequence(path=str(script_path))
    assert "$HOME" in str(result["stdout"])


def test_background_start_collect(sim_client: SSHClientWrapper) -> None:
    sim_client.start("cat /etc/version", "bg")
    result = sim_client.collect("bg")
    assert "v1.2.3" in str(result["stdout"])
    assert result["exit_code"] == 0


def test_close_harvests_background_job(sim_client: SSHClientWrapper) -> None:
    sim_client.start("uname -a", "harvest")
    sim_client.close()
    stdout_path = sim_client._jobs["harvest"].stdout_path  # noqa: SLF001
    assert stdout_path.exists()


def test_sftp_get_glob_and_newest(sim_client: SSHClientWrapper) -> None:
    written = sim_client.sftp_get("/var/log/*.log", "logs", newest=1)
    assert len(written) == 1


def test_sftp_get_single_file_rename(sim_client: SSHClientWrapper) -> None:
    written = sim_client.sftp_get("/etc/network/interfaces", "host_a_interfaces")
    assert len(written) == 1
    assert written[0].endswith("host_a_interfaces")


def test_sftp_listdir_mkdir_remove_rename(sim_client: SSHClientWrapper) -> None:
    sim_client.sftp_mkdir("/tmp/newdir")
    names = sim_client.sftp_listdir("/var/log")
    assert "a.log" in names
    sim_client.sftp_rename("/var/log/a.log", "/var/log/renamed.log")
    sim_client.sftp_remove("/var/log/renamed.log")


def test_scp_get_delegates_to_sim_sftp(sim_client: SSHClientWrapper) -> None:
    scp = ScpClientWrapper(sim_client)
    written = scp.get("/etc/network/interfaces", "scp_interfaces")
    assert len(written) == 1


def test_windows_platform_glob_case_insensitive() -> None:
    client = SSHClientWrapper(
        {"driver": "sim", "host": "sim.local", "username": "win", "platform": "windows"},
    )
    files = client.resolve_remote_files("C:/logs/*.LOG")
    assert len(files) == 2
