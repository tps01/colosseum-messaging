"""Bounded connection retries close failures and never replay operations."""

import errno
import socket
from unittest.mock import Mock

import paramiko
import pytest
from colosseum.config import load_config
from colosseum.config.loader import ConfigError
from colosseum.context import init_context
from colosseum_messaging.connections import get_ssh_client
from colosseum_messaging.ssh import api
from colosseum_messaging.ssh.client import SSHClientWrapper, _HostKeyError

CONFIG = {"host": "bench.example", "username": "user", "password": "secret"}
JUMP = {
    "jump_host": "jump.example",
    "jump_username": "jump-user",
    "jump_password": "jump-secret",
    "jump_port": 2222,
}


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


def test_jump_fields_route_endpoint_connection_and_close_both_hops(tmp_path, clients):
    created, _ = clients
    init_context(test_case_name="ssh_jump", no_artifacts=True)
    config = tmp_path / "config.toml"
    config.write_text(
        '[messaging.ssh]\nssh_id = 1\nhost = "bench.example"\nport = 2022\n'
        'username = "user"\npassword = "secret"\ntimeout = 2.5\n'
        'jump_host = "jump.example"\njump_port = 2222\n'
        'jump_username = "jump-user"\njump_password = "jump-secret"\n',
        encoding="utf-8",
    )
    load_config(config)

    wrapper = get_ssh_client(1, retries=1)
    jump, endpoint = created
    jump.connect.assert_called_once_with(
        hostname="jump.example",
        port=2222,
        username="jump-user",
        password="jump-secret",
        timeout=2.5,
        banner_timeout=2.5,
        auth_timeout=2.5,
        allow_agent=False,
        look_for_keys=False,
    )
    forward = jump.get_transport.return_value.open_channel
    forward.assert_called_once_with(
        "direct-tcpip", dest_addr=("bench.example", 2022), src_addr=("127.0.0.1", 0), timeout=2.5,
    )
    endpoint.connect.assert_called_once_with(
        hostname="bench.example",
        port=2022,
        username="user",
        password="secret",
        sock=forward.return_value,
        timeout=2.5,
        banner_timeout=2.5,
        auth_timeout=2.5,
        allow_agent=False,
        look_for_keys=False,
    )
    assert wrapper.get_transport() is endpoint.get_transport.return_value
    assert get_ssh_client(1) is wrapper
    wrapper.close()
    wrapper.close()
    endpoint.close.assert_called_once_with()
    forward.return_value.close.assert_called_once_with()
    jump.close.assert_called_once_with()


@pytest.mark.parametrize("error", [TimeoutError(), paramiko.AuthenticationException("endpoint denied")])
def test_jump_releases_failed_hops_and_retries_only_transient_errors(clients, error):
    created, outcomes = clients
    outcomes.extend([None, error])
    config = {**CONFIG, **JUMP}
    if isinstance(error, TimeoutError):
        with_retry = SSHClientWrapper(config, retries=2)
        assert len(created) == 4
        assert with_retry.get_transport() is created[-1].get_transport.return_value
        with_retry.close()
    else:
        with pytest.raises(paramiko.AuthenticationException):
            SSHClientWrapper(config, retries=2)
        assert len(created) == 2
    bad_jump, bad_endpoint = created[:2]
    bad_endpoint.close.assert_called_once_with()
    bad_jump.get_transport.return_value.open_channel.return_value.close.assert_called_once_with()
    bad_jump.close.assert_called_once_with()


def test_jump_requires_separate_password_before_opening(clients):
    created, _ = clients
    with pytest.raises(ValueError, match=r"messaging\.ssh\.jump_password"):
        SSHClientWrapper({**CONFIG, "jump_host": JUMP["jump_host"], "jump_username": JUMP["jump_username"]})
    assert not created


@pytest.mark.parametrize("override", [False, True])
def test_jump_id_uses_the_referenced_ssh_row(tmp_path, clients, override):
    created, _ = clients
    init_context(test_case_name="ssh_jump_id", no_artifacts=True)
    referenced_keys = tmp_path / "jump_keys"
    override_keys = tmp_path / "override_keys"
    overrides = f'jump_port = 2223\njump_known_hosts = "{override_keys.as_posix()}"\n' if override else ""
    config = tmp_path / "config.toml"
    config.write_text(
        '[[messaging.ssh]]\nssh_id = 1\nhost = "bench.example"\nusername = "user"\npassword = "secret"\njump_id = 2\n'
        f'{overrides}[[messaging.ssh]]\nssh_id = 2\nhost = "jump.example"\nusername = "jump-user"\n'
        f'password = "jump-secret"\nport = "2222"\nknown_hosts = "{referenced_keys.as_posix()}"\n',
        encoding="utf-8",
    )
    store = load_config(config)

    wrapper = get_ssh_client(1, retries=1)
    try:
        jump, endpoint = created
        jump_args = jump.connect.call_args.kwargs
        assert jump_args["hostname"] == "jump.example"
        assert jump_args["username"] == "jump-user"
        assert jump_args["password"] == "jump-secret"
        assert jump_args["port"] == (2223 if override else 2222)
        jump.load_host_keys.assert_called_once_with(str(override_keys if override else referenced_keys))
        endpoint_args = endpoint.connect.call_args.kwargs
        assert endpoint_args["hostname"] == "bench.example"
        assert endpoint_args["password"] == "secret"
        assert endpoint_args["sock"] is jump.get_transport.return_value.open_channel.return_value
        assert "jump_password" not in store.require_item("messaging.ssh", 1)
    finally:
        wrapper.close()


@pytest.mark.parametrize(
    ("jump_settings", "message"),
    [
        ("jump_id = true", "jump_id must be an integer"),
        ("jump_id = 1", "jump_id must reference another SSH row"),
        ("jump_id = 99", "Unknown id"),
        ('jump_id = 2\njump_password = "duplicate"', "Choose either messaging.ssh.jump_id"),
        ("jump_id = 2", "SSH row without a nonempty password"),
    ],
)
def test_invalid_jump_id_fails_before_opening(tmp_path, clients, jump_settings, message):
    created, _ = clients
    init_context(test_case_name="invalid_ssh_jump_id", no_artifacts=True)
    config = tmp_path / "config.toml"
    config.write_text(
        '[[messaging.ssh]]\nssh_id = 1\nhost = "bench.example"\nusername = "user"\n'
        f'{jump_settings}\n[[messaging.ssh]]\nssh_id = 2\nhost = "jump.example"\nusername = "jump-user"\n',
        encoding="utf-8",
    )
    load_config(config)

    with pytest.raises(ConfigError, match=message):
        get_ssh_client(1)
    assert not created


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


@pytest.mark.parametrize(
    "failure",
    [
        paramiko.AuthenticationException("denied"),
        paramiko.BadHostKeyException("host", Mock(), Mock()),
        FileNotFoundError(errno.ENOENT, "missing key"),
        PermissionError(errno.EACCES, "cannot read key"),
        socket.gaierror(socket.EAI_NONAME, "no host"),
    ],
)
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
