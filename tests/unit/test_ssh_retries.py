"""Bounded connection retries close failures and never replay operations."""

import errno
import socket
from unittest.mock import Mock

import paramiko
import pytest
from colosseum.config import load_config
from colosseum.context import init_context
from colosseum_messaging.connections import get_ssh_client
from colosseum_messaging.ssh import api
from colosseum_messaging.ssh.client import SSHClientWrapper, _HostKeyError

CONFIG = {"host": "bench.example", "username": "user", "password": "secret"}


@pytest.fixture
def clients(monkeypatch):
    created = []
    real_client = paramiko.SSHClient
    outcomes = []

    def create():
        client = Mock(spec=real_client)
        if outcomes:
            client.connect.side_effect = outcomes.pop(0)
        created.append(client)
        return client

    monkeypatch.setattr(paramiko, "SSHClient", create)
    return created, outcomes


def test_default_retry_succeeds_with_fresh_clients_and_default_timeouts(clients):
    created, outcomes = clients
    outcomes.extend([TimeoutError(), paramiko.SSHException("Error reading SSH protocol banner")])
    wrapper = SSHClientWrapper(CONFIG)
    assert len(created) == 3
    assert wrapper._require_client() is created[-1]
    for client in created:
        kwargs = client.connect.call_args.kwargs
        assert kwargs["timeout"] == kwargs["banner_timeout"] == kwargs["auth_timeout"] == 10.0
        assert kwargs["allow_agent"] is False
        assert kwargs["look_for_keys"] is False
    assert [c.close.call_count for c in created] == [1, 1, 0]
    wrapper.close()
    created[-1].close.assert_called_once()


@pytest.mark.parametrize("retries,expected", [(None, 3), (0, 1), (1, 1), (2, 2), (5, 5)])
def test_exhaustion_preserves_final_exception_and_closes_every_attempt(clients, retries, expected):
    created, outcomes = clients
    error = ConnectionRefusedError("offline")
    outcomes.extend([error] * expected)
    kwargs = {} if retries is None else {"retries": retries}
    with pytest.raises(ConnectionRefusedError) as caught:
        SSHClientWrapper({**CONFIG, "timeout": 2.5}, **kwargs)
    assert caught.value is error
    assert len(created) == expected
    for client in created:
        client.close.assert_called_once()
        assert client.connect.call_args.kwargs["auth_timeout"] == 2.5


@pytest.mark.parametrize("failure", [
    paramiko.AuthenticationException("denied"),
    paramiko.BadHostKeyException("host", Mock(), Mock()),
    FileNotFoundError(errno.ENOENT, "missing key"),
    PermissionError(errno.EACCES, "cannot read key"),
    socket.gaierror(socket.EAI_NONAME, "no host"),
])
def test_permanent_failures_are_not_retried(clients, failure):
    created, outcomes = clients
    outcomes.append(failure)
    with pytest.raises(type(failure)) as caught:
        SSHClientWrapper(CONFIG)
    assert caught.value is failure
    assert len(created) == 1
    created[0].close.assert_called_once()


def test_auth_none_host_key_rejection_is_not_retried(monkeypatch):
    connect = Mock(side_effect=_HostKeyError("SSH host key is not in known_hosts"))
    monkeypatch.setattr(SSHClientWrapper, "_connect_auth_none", connect)
    with pytest.raises(paramiko.SSHException, match="not in known_hosts"):
        SSHClientWrapper({**CONFIG, "auth": "none"})
    connect.assert_called_once()


@pytest.mark.parametrize("retries", [-1, True, 1.5, "3"])
def test_invalid_attempt_counts_fail_before_opening(clients, retries):
    created, _ = clients
    with pytest.raises(ValueError, match="retries"):
        SSHClientWrapper(CONFIG, retries=retries)
    assert not created


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), "bad"])
def test_invalid_timeout_fails_before_opening(clients, timeout):
    created, _ = clients
    with pytest.raises(ValueError):
        SSHClientWrapper({**CONFIG, "timeout": timeout})
    assert not created


@pytest.mark.parametrize("failure_stage", ["start_client", "auth_none"])
def test_auth_none_retries_close_transport_and_bound_tcp(monkeypatch, failure_stage):
    sockets, transports = [], []
    real_socket, real_transport = socket.socket, paramiko.Transport

    def connect(address, timeout):
        assert address == ("bench.example", 22)
        assert timeout == 10.0
        sock = Mock(spec=real_socket)
        sockets.append(sock)
        return sock

    def transport(sock):
        item = Mock(spec=real_transport)
        if not transports:
            getattr(item, failure_stage).side_effect = EOFError("disconnected")
        transports.append(item)
        return item

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(paramiko, "Transport", transport)
    monkeypatch.setattr(SSHClientWrapper, "_require_known_host_key", Mock())
    wrapper = SSHClientWrapper({**CONFIG, "auth": "none"})
    assert len(transports) == 2
    transports[0].close.assert_called_once()
    sockets[0].close.assert_called_once()
    for item in transports:
        assert item.banner_timeout == item.auth_timeout == 10.0
        item.start_client.assert_called_once_with(timeout=10.0)
    assert wrapper.get_transport() is transports[-1]
    wrapper.close()


def test_auth_none_rejects_auth_without_retry_and_closes_socket(monkeypatch):
    sock = Mock(spec=socket.socket)
    transport = Mock(spec=paramiko.Transport)
    transport.auth_none.side_effect = paramiko.AuthenticationException("denied")
    connect = Mock(return_value=sock)
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(paramiko, "Transport", Mock(return_value=transport))
    monkeypatch.setattr(SSHClientWrapper, "_require_known_host_key", Mock())
    with pytest.raises(paramiko.AuthenticationException):
        SSHClientWrapper({**CONFIG, "auth": "none"})
    connect.assert_called_once()
    transport.close.assert_called_once()
    sock.close.assert_called_once()


def test_failed_connections_are_not_cached_and_commands_are_not_replayed(tmp_path, clients):
    created, outcomes = clients
    outcomes.extend([TimeoutError()] * 2)
    ctx = init_context(test_case_name="retry_cache", no_artifacts=True)
    config = tmp_path / "config.toml"
    config.write_text(
        '[messaging.ssh]\nssh_id = 1\nhost = "bench.example"\nusername = "user"\n',
        encoding="utf-8",
    )
    load_config(config)
    with pytest.raises(TimeoutError):
        api.measure_stdout.__wrapped__(ssh_id=1, command="echo once", key="open", retries=2)
    assert "messaging:ssh:1" not in ctx.resource_cache
    wrapper = get_ssh_client(1, retries=1)
    assert get_ssh_client(1, retries=5) is wrapper
    assert len(created) == 3
    remote = created[-1]
    remote.exec_command.side_effect = EOFError("command may have started")
    with pytest.raises(EOFError):
        api.exec.__wrapped__(ssh_id=1, command="side-effect", key="cmd", retries=4)
    assert remote.exec_command.call_count == 1
    assert len(created) == 3
    wrapper.close()
